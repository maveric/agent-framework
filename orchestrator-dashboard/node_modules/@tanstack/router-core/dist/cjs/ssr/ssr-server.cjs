"use strict";
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
const seroval = require("seroval");
const invariant = require("tiny-invariant");
const utils = require("../utils.cjs");
const tsrScript = require("./tsrScript.cjs");
const constants = require("./constants.cjs");
const serovalPlugins = require("./serializer/seroval-plugins.cjs");
const transformer = require("./serializer/transformer.cjs");
const transformStreamWithRouter = require("./transformStreamWithRouter.cjs");
const SCOPE_ID = "tsr";
function dehydrateMatch(match) {
  const dehydratedMatch = {
    i: match.id,
    u: match.updatedAt,
    s: match.status
  };
  const properties = [
    ["__beforeLoadContext", "b"],
    ["loaderData", "l"],
    ["error", "e"],
    ["ssr", "ssr"]
  ];
  for (const [key, shorthand] of properties) {
    if (match[key] !== void 0) {
      dehydratedMatch[shorthand] = match[key];
    }
  }
  return dehydratedMatch;
}
const INITIAL_SCRIPTS = [
  seroval.getCrossReferenceHeader(SCOPE_ID),
  tsrScript
];
class ScriptBuffer {
  constructor(router) {
    this._queue = [...INITIAL_SCRIPTS];
    this._scriptBarrierLifted = false;
    this._cleanedUp = false;
    this.router = router;
  }
  enqueue(script) {
    if (this._cleanedUp) return;
    if (this._scriptBarrierLifted && this._queue.length === 0) {
      queueMicrotask(() => {
        this.injectBufferedScripts();
      });
    }
    this._queue.push(script);
  }
  liftBarrier() {
    if (this._scriptBarrierLifted || this._cleanedUp) return;
    this._scriptBarrierLifted = true;
    if (this._queue.length > 0) {
      queueMicrotask(() => {
        this.injectBufferedScripts();
      });
    }
  }
  takeAll() {
    const bufferedScripts = this._queue;
    this._queue = [];
    if (bufferedScripts.length === 0) {
      return void 0;
    }
    bufferedScripts.push(`${constants.GLOBAL_TSR}.c()`);
    const joinedScripts = bufferedScripts.join(";");
    return joinedScripts;
  }
  injectBufferedScripts() {
    if (this._cleanedUp) return;
    const scriptsToInject = this.takeAll();
    if (scriptsToInject && this.router?.serverSsr) {
      this.router.serverSsr.injectScript(() => scriptsToInject);
    }
  }
  cleanup() {
    this._cleanedUp = true;
    this._queue = [];
    this.router = void 0;
  }
}
function attachRouterServerSsrUtils({
  router,
  manifest
}) {
  router.ssr = {
    manifest
  };
  let _dehydrated = false;
  const listeners = [];
  const scriptBuffer = new ScriptBuffer(router);
  router.serverSsr = {
    injectedHtml: [],
    injectHtml: (getHtml) => {
      const promise = Promise.resolve().then(getHtml);
      router.serverSsr.injectedHtml.push(promise);
      router.emit({
        type: "onInjectedHtml",
        promise
      });
      return promise.then(() => {
      });
    },
    injectScript: (getScript) => {
      return router.serverSsr.injectHtml(async () => {
        const script = await getScript();
        if (!script) {
          return "";
        }
        return `<script${router.options.ssr?.nonce ? ` nonce='${router.options.ssr.nonce}'` : ""} class='$tsr'>${script}<\/script>`;
      });
    },
    dehydrate: async () => {
      invariant(!_dehydrated, "router is already dehydrated!");
      let matchesToDehydrate = router.state.matches;
      if (router.isShell()) {
        matchesToDehydrate = matchesToDehydrate.slice(0, 1);
      }
      const matches = matchesToDehydrate.map(dehydrateMatch);
      let manifestToDehydrate = void 0;
      if (manifest) {
        const filteredRoutes = Object.fromEntries(
          router.state.matches.map((k) => [
            k.routeId,
            manifest.routes[k.routeId]
          ])
        );
        manifestToDehydrate = {
          routes: filteredRoutes
        };
      }
      const dehydratedRouter = {
        manifest: manifestToDehydrate,
        matches
      };
      const lastMatchId = matchesToDehydrate[matchesToDehydrate.length - 1]?.id;
      if (lastMatchId) {
        dehydratedRouter.lastMatchId = lastMatchId;
      }
      const dehydratedData = await router.options.dehydrate?.();
      if (dehydratedData) {
        dehydratedRouter.dehydratedData = dehydratedData;
      }
      _dehydrated = true;
      const p = utils.createControlledPromise();
      const trackPlugins = { didRun: false };
      const plugins = router.options.serializationAdapters?.map((t) => transformer.makeSsrSerovalPlugin(t, trackPlugins)) ?? [];
      seroval.crossSerializeStream(dehydratedRouter, {
        refs: /* @__PURE__ */ new Map(),
        plugins: [...plugins, ...serovalPlugins.defaultSerovalPlugins],
        onSerialize: (data, initial) => {
          let serialized = initial ? constants.GLOBAL_TSR + ".router=" + data : data;
          if (trackPlugins.didRun) {
            serialized = constants.GLOBAL_TSR + ".p(()=>" + serialized + ")";
          }
          scriptBuffer.enqueue(serialized);
        },
        scopeId: SCOPE_ID,
        onDone: () => {
          scriptBuffer.enqueue(constants.GLOBAL_TSR + ".streamEnd=true");
          p.resolve("");
        },
        onError: (err) => p.reject(err)
      });
      router.serverSsr.injectHtml(() => p);
    },
    isDehydrated() {
      return _dehydrated;
    },
    onRenderFinished: (listener) => listeners.push(listener),
    setRenderFinished: () => {
      listeners.forEach((l) => l());
      listeners.length = 0;
      scriptBuffer.liftBarrier();
    },
    takeBufferedScripts() {
      const scripts = scriptBuffer.takeAll();
      const serverBufferedScript = {
        tag: "script",
        attrs: {
          nonce: router.options.ssr?.nonce,
          className: "$tsr",
          id: transformStreamWithRouter.TSR_SCRIPT_BARRIER_ID
        },
        children: scripts
      };
      return serverBufferedScript;
    },
    liftScriptBarrier() {
      scriptBuffer.liftBarrier();
    },
    cleanup() {
      if (!router.serverSsr) return;
      listeners.length = 0;
      scriptBuffer.cleanup();
      router.serverSsr.injectedHtml = [];
      router.serverSsr = void 0;
    }
  };
}
function getOrigin(request) {
  const originHeader = request.headers.get("Origin");
  if (originHeader) {
    try {
      new URL(originHeader);
      return originHeader;
    } catch {
    }
  }
  try {
    return new URL(request.url).origin;
  } catch {
  }
  return "http://localhost";
}
exports.attachRouterServerSsrUtils = attachRouterServerSsrUtils;
exports.dehydrateMatch = dehydrateMatch;
exports.getOrigin = getOrigin;
//# sourceMappingURL=ssr-server.cjs.map
