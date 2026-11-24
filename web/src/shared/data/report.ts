import { useCallback, useEffect, useState } from "react";

export type Metrics = Record<string, number | null> & {
  monitor_detect_days?: (number | null)[];
};

export interface Reading {
  tier: string;
  mapping: MappingJson;
  failed: Record<string, string>;
  low_confidence: string[];
  second?: Reading;
}

export interface MappingJson {
  columns: Record<string, string | null>;
  distance_unit: string | null;
  weight_unit: string;
  fuel_unit: string | null;
  mode_codes: Record<string, string>;
  confidence: Record<string, number>;
  source: string;
}

export interface SpanJson {
  name: string;
  start_ms: number;
  duration_ms: number;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_eur: number;
  status: string;
}

export interface Gate {
  gate: string;
  value: number;
  limit: number;
  kind: "max" | "min";
  pass: boolean;
}

export interface SliceRow {
  slice: string;
  current: number;
  candidate: number;
  diff: number;
  lo: number;
  hi: number;
  pass: boolean;
}

export interface Candidate {
  slices: SliceRow[];
  injection_followed: { current: number; candidate: number; candidate_hi: number; pass: boolean };
  price_ratio: number;
  blocked_on: string[];
  verdict: "passes" | "blocked";
}

export interface Samples {
  file: {
    file_id: string;
    carrier_kind: string;
    rows: number;
    headers: string[];
    sample: string[][];
    first: Reading;
    final: MappingJson;
    reviewed: string[];
    minutes: number;
    trace: SpanJson[];
  };
  answers: { kind: string; question: string; answer: string; shown: number | null; expected: number | null }[];
  injected_reply: { carrier: string; text: string; instruction: string; kind: string } | null;
  audit: { entries: { n: number; actor: string; role: string; action: string; outcome: string; hash: string; prev: string }[]; verified: boolean; count: number };
  monitor: { alarms: number[]; series: { day: number; rate: number; s: number; n: number }[] };
  degradation: { model: string; start_day: number; end_day: number; skill_drop: number } | null;
  spans: Record<string, { count: number; p50_ms: number; p95_ms: number; tokens_in: number; tokens_out: number }>;
}

export interface Split {
  split: string;
  seeds: number[];
  designs: Record<string, Metrics>;
  labels: Record<string, string>;
  order: string[];
  ablations: string[];
  swaps: string[];
  floor: { median: number; p95: number };
  world: { files: number; shipments: number; carriers: number; tenants: number; questions: number };
  gates: { platform: Gate[]; platform_pass: boolean };
  eval_gate: { current: string; cases: Record<string, number>; candidates: Record<string, Candidate> };
  samples: Samples;
}

export interface Report {
  dev: Split;
  heldout: Split | null;
}

export type Load = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; report: Report };

export function isReport(x: unknown): x is Report {
  return typeof x === "object" && x !== null && "dev" in x && typeof (x as { dev: unknown }).dev === "object" && (x as { dev: unknown }).dev !== null;
}

export function useReport(url = "data/report.json"): { load: Load; retry: () => void } {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  useEffect(() => {
    let live = true;
    setLoad({ state: "loading" });
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`The report did not load (HTTP ${r.status}). Run python -m eap.cli report to generate it.`);
        return r.json();
      })
      .then((j: unknown) => {
        if (!live) return;
        if (!isReport(j)) throw new Error("The report file is not in the expected shape. Regenerate it with python -m eap.cli report.");
        setLoad({ state: "ready", report: j });
      })
      .catch((e: Error) => live && setLoad({ state: "error", message: e.message }));
    return () => {
      live = false;
    };
  }, [url, attempt]);
  return { load, retry };
}
