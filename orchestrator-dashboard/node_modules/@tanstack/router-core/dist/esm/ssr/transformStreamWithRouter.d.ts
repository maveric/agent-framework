import { ReadableStream } from 'node:stream/web';
import { Readable } from 'node:stream';
import { AnyRouter } from '../router.js';
export declare function transformReadableStreamWithRouter(router: AnyRouter, routerStream: ReadableStream): ReadableStream<any>;
export declare function transformPipeableStreamWithRouter(router: AnyRouter, routerStream: Readable): Readable;
export declare const TSR_SCRIPT_BARRIER_ID = "$tsr-stream-barrier";
export declare function transformStreamWithRouter(router: AnyRouter, appStream: ReadableStream, opts?: {
    timeoutMs?: number;
}): ReadableStream<any>;
