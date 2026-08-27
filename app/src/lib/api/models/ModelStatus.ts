/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Response model for model status.
 */
export type ModelStatus = {
  model_name: string;
  display_name: string;
  downloaded: boolean;
  downloading?: boolean; // True if download is in progress
  size_mb?: number | null;
  loaded?: boolean;
  engine?: string | null;
  supported?: boolean; // Whether the engine can run on this machine
  support_note?: string | null; // e.g. "Runs on CPU on Apple Silicon (no Metal path)"
  needs_token?: boolean; // Gated repo requires an authenticated HF token
  note?: string | null; // Static per-config note (licensing / gating hints)
};
