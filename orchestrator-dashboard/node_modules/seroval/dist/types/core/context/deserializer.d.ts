import type { PluginAccessOptions } from '../plugin';
import { SerovalMode } from '../plugin';
import type { SerovalNode } from '../types';
export interface BaseDeserializerContextOptions extends PluginAccessOptions {
    refs?: Map<number, unknown>;
}
export interface BaseDeserializerContext extends PluginAccessOptions {
    readonly mode: SerovalMode;
    /**
     * Mapping ids to values
     */
    refs: Map<number, unknown>;
}
export declare function createBaseDeserializerContext(mode: SerovalMode, options: BaseDeserializerContextOptions): BaseDeserializerContext;
export interface VanillaDeserializerContextOptions extends Omit<BaseDeserializerContextOptions, 'refs'> {
    markedRefs: number[] | Set<number>;
}
export interface VanillaDeserializerState {
    marked: Set<number>;
}
export interface VanillaDeserializerContext {
    mode: SerovalMode.Vanilla;
    base: BaseDeserializerContext;
    child: DeserializePluginContext | undefined;
    state: VanillaDeserializerState;
}
export declare function createVanillaDeserializerContext(options: VanillaDeserializerContextOptions): VanillaDeserializerContext;
export interface CrossDeserializerContext {
    mode: SerovalMode.Cross;
    base: BaseDeserializerContext;
    child: DeserializePluginContext | undefined;
}
export type CrossDeserializerContextOptions = BaseDeserializerContextOptions;
export declare function createCrossDeserializerContext(options: CrossDeserializerContextOptions): CrossDeserializerContext;
type DeserializerContext = VanillaDeserializerContext | CrossDeserializerContext;
export declare class DeserializePluginContext {
    private _p;
    constructor(_p: DeserializerContext);
    deserialize<T>(node: SerovalNode): T;
}
export declare function deserialize(ctx: DeserializerContext, node: SerovalNode): unknown;
export declare function deserializeTop(ctx: DeserializerContext, node: SerovalNode): unknown;
export {};
//# sourceMappingURL=deserializer.d.ts.map