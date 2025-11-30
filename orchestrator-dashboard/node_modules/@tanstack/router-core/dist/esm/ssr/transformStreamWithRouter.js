import { ReadableStream } from "node:stream/web";
import { Readable } from "node:stream";
import { createControlledPromise } from "../utils.js";
function transformReadableStreamWithRouter(router, routerStream) {
  return transformStreamWithRouter(router, routerStream);
}
function transformPipeableStreamWithRouter(router, routerStream) {
  return Readable.fromWeb(
    transformStreamWithRouter(router, Readable.toWeb(routerStream))
  );
}
const TSR_SCRIPT_BARRIER_ID = "$tsr-stream-barrier";
const patternBodyEnd = /(<\/body>)/;
const patternHtmlEnd = /(<\/html>)/;
const patternClosingTag = /(<\/[a-zA-Z][\w:.-]*?>)/g;
function createPassthrough(onCancel) {
  let controller;
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(c) {
      controller = c;
    },
    cancel() {
      res.destroyed = true;
      onCancel();
    }
  });
  const res = {
    stream,
    write: (chunk) => {
      if (res.destroyed) return;
      if (typeof chunk === "string") {
        controller.enqueue(encoder.encode(chunk));
      } else {
        controller.enqueue(chunk);
      }
    },
    end: (chunk) => {
      if (res.destroyed) return;
      if (chunk) {
        res.write(chunk);
      }
      res.destroyed = true;
      controller.close();
    },
    destroy: (error) => {
      if (res.destroyed) return;
      res.destroyed = true;
      controller.error(error);
    },
    destroyed: false
  };
  return res;
}
async function readStream(stream, opts) {
  const reader = stream.getReader();
  try {
    let chunk;
    while (!(chunk = await reader.read()).done) {
      opts.onData?.(chunk);
    }
    opts.onEnd?.();
  } catch (error) {
    opts.onError?.(error);
  } finally {
    reader.releaseLock();
  }
}
function transformStreamWithRouter(router, appStream, opts) {
  let stopListeningToInjectedHtml = void 0;
  let timeoutHandle;
  let cleanedUp = false;
  function cleanup() {
    if (cleanedUp) return;
    cleanedUp = true;
    if (stopListeningToInjectedHtml) {
      stopListeningToInjectedHtml();
      stopListeningToInjectedHtml = void 0;
    }
    clearTimeout(timeoutHandle);
    router.serverSsr?.cleanup();
  }
  const finalPassThrough = createPassthrough(cleanup);
  const textDecoder = new TextDecoder();
  let isAppRendering = true;
  let routerStreamBuffer = "";
  let pendingClosingTags = "";
  let streamBarrierLifted = false;
  let leftover = "";
  let leftoverHtml = "";
  function getBufferedRouterStream() {
    const html = routerStreamBuffer;
    routerStreamBuffer = "";
    return html;
  }
  function decodeChunk(chunk) {
    if (chunk instanceof Uint8Array) {
      return textDecoder.decode(chunk, { stream: true });
    }
    return String(chunk);
  }
  const injectedHtmlDonePromise = createControlledPromise();
  let processingCount = 0;
  handleInjectedHtml();
  stopListeningToInjectedHtml = router.subscribe(
    "onInjectedHtml",
    handleInjectedHtml
  );
  function handleInjectedHtml() {
    if (cleanedUp) return;
    router.serverSsr.injectedHtml.forEach((promise) => {
      processingCount++;
      promise.then((html) => {
        if (cleanedUp || finalPassThrough.destroyed) {
          return;
        }
        if (isAppRendering) {
          routerStreamBuffer += html;
        } else {
          finalPassThrough.write(html);
        }
      }).catch((err) => {
        injectedHtmlDonePromise.reject(err);
      }).finally(() => {
        processingCount--;
        if (!isAppRendering && processingCount === 0) {
          injectedHtmlDonePromise.resolve();
        }
      });
    });
    router.serverSsr.injectedHtml = [];
  }
  injectedHtmlDonePromise.then(() => {
    if (cleanedUp || finalPassThrough.destroyed) {
      return;
    }
    clearTimeout(timeoutHandle);
    const finalHtml = leftover + leftoverHtml + getBufferedRouterStream() + pendingClosingTags;
    leftover = "";
    leftoverHtml = "";
    pendingClosingTags = "";
    finalPassThrough.end(finalHtml);
  }).catch((err) => {
    if (cleanedUp || finalPassThrough.destroyed) {
      return;
    }
    console.error("Error reading routerStream:", err);
    finalPassThrough.destroy(err);
  }).finally(cleanup);
  readStream(appStream, {
    onData: (chunk) => {
      if (cleanedUp || finalPassThrough.destroyed) {
        return;
      }
      const text = decodeChunk(chunk.value);
      const chunkString = leftover + text;
      const bodyEndMatch = chunkString.match(patternBodyEnd);
      const htmlEndMatch = chunkString.match(patternHtmlEnd);
      if (!streamBarrierLifted) {
        const streamBarrierIdIncluded = chunkString.includes(
          TSR_SCRIPT_BARRIER_ID
        );
        if (streamBarrierIdIncluded) {
          streamBarrierLifted = true;
          router.serverSsr.liftScriptBarrier();
        }
      }
      if (bodyEndMatch && htmlEndMatch && bodyEndMatch.index < htmlEndMatch.index) {
        const bodyEndIndex = bodyEndMatch.index;
        pendingClosingTags = chunkString.slice(bodyEndIndex);
        finalPassThrough.write(
          chunkString.slice(0, bodyEndIndex) + getBufferedRouterStream() + leftoverHtml
        );
        leftover = "";
        leftoverHtml = "";
        return;
      }
      let result;
      let lastIndex = 0;
      patternClosingTag.lastIndex = 0;
      while ((result = patternClosingTag.exec(chunkString)) !== null) {
        lastIndex = result.index + result[0].length;
      }
      if (lastIndex > 0) {
        const processed = chunkString.slice(0, lastIndex) + getBufferedRouterStream() + leftoverHtml;
        finalPassThrough.write(processed);
        leftover = chunkString.slice(lastIndex);
        leftoverHtml = "";
      } else {
        leftover = chunkString;
        leftoverHtml += getBufferedRouterStream();
      }
    },
    onEnd: () => {
      if (cleanedUp || finalPassThrough.destroyed) {
        return;
      }
      isAppRendering = false;
      router.serverSsr.setRenderFinished();
      if (processingCount === 0) {
        injectedHtmlDonePromise.resolve();
      } else {
        const timeoutMs = opts?.timeoutMs ?? 6e4;
        timeoutHandle = setTimeout(() => {
          injectedHtmlDonePromise.reject(
            new Error("Injected HTML timeout after app render finished")
          );
        }, timeoutMs);
      }
    },
    onError: (error) => {
      if (cleanedUp) {
        return;
      }
      console.error("Error reading appStream:", error);
      isAppRendering = false;
      router.serverSsr.setRenderFinished();
      clearTimeout(timeoutHandle);
      leftover = "";
      leftoverHtml = "";
      routerStreamBuffer = "";
      pendingClosingTags = "";
      finalPassThrough.destroy(error);
      injectedHtmlDonePromise.reject(error);
    }
  });
  return finalPassThrough.stream;
}
export {
  TSR_SCRIPT_BARRIER_ID,
  transformPipeableStreamWithRouter,
  transformReadableStreamWithRouter,
  transformStreamWithRouter
};
//# sourceMappingURL=transformStreamWithRouter.js.map
