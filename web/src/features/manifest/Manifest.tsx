import { motion, useReducedMotion } from "framer-motion";
import { useMemo, useState } from "react";
import type { MappingJson, Samples } from "../../shared/data/report";
import { fieldName, modeName } from "../../shared/format";
import styles from "./manifest.module.css";

type Step = "first" | "second" | "final";
const STEP_LABEL: Record<Step, string> = { first: "First read (small model)", second: "Second read (mid-size model)", final: "After a person" };

interface Cell {
  field: string | null;
  fields: string[];
  unit: string | null;
  codes: [string, string][];
  verdict: "fail" | "person" | "ok" | "unused";
  reasons: string[];
}

function cellsFor(headers: string[], m: MappingJson, failed: Record<string, string>, reviewed: string[]): Cell[] {
  const byHeader = new Map<string, string[]>();
  for (const [f, h] of Object.entries(m.columns)) if (h) byHeader.set(h, [...(byHeader.get(h) ?? []), f]);
  return headers.map((h) => {
    const fields = byHeader.get(h) ?? [];
    const field = fields.find((f) => f === "weight" || f === "distance" || f === "mode") ?? fields[0] ?? null;
    if (!field) return { field: null, fields: [], unit: null, codes: [], verdict: "unused", reasons: [] };
    const keys = fields.map((f) => `col:${f}`);
    let unit: string | null = null;
    if (field === "weight") {
      unit = m.weight_unit;
      keys.push("unit:weight");
    }
    if (field === "distance") {
      unit = m.distance_unit;
      keys.push("unit:distance");
    }
    const codes: [string, string][] = field === "mode" ? Object.entries(m.mode_codes) : [];
    if (field === "mode") keys.push(...codes.map(([c]) => `code:${c}`));
    const reasons = keys.filter((k) => failed[k]).map((k) => failed[k] as string);
    const touched = keys.some((k) => reviewed.includes(k));
    return { field, fields, unit, codes, verdict: reasons.length ? "fail" : touched ? "person" : "ok", reasons: [...new Set(reasons)] };
  });
}

export function Manifest({ file }: { file: Samples["file"] }) {
  const [step, setStep] = useState<Step>("final");
  const reduce = useReducedMotion();
  const steps: Step[] = file.first.second ? ["first", "second", "final"] : ["first", "final"];
  const reading = step === "first" ? file.first : step === "second" ? file.first.second : null;
  const cells = useMemo(
    () => cellsFor(file.headers, reading ? reading.mapping : file.final, reading ? reading.failed : {}, reading ? [] : file.reviewed),
    [file, reading],
  );
  const failedCount = Object.keys(file.first.failed).length;
  return (
    <section className={styles.wrap} aria-labelledby="manifest-title">
      <div className={styles.intro}>
        <h1 id="manifest-title" className={styles.title}>
          A carrier file, read by agents and checked by code
        </h1>
        <p className={styles.lede}>
          {file.rows} shipments from an {file.carrier_kind} carrier, in the carrier's own headers. The small model read it first and code
          rejected {failedCount} of its decisions; the mid-size model read it again; a person settled what code still would not accept, in{" "}
          {Math.round(file.minutes)} minutes. Step through the readings.
        </p>
      </div>
      <div className={styles.steps} role="tablist" aria-label="Readings of this file">
        {steps.map((s) => (
          <button key={s} type="button" role="tab" aria-selected={step === s} className={styles.step} onClick={() => setStep(s)}>
            {step === s && <motion.span layoutId="step-pill" className={styles.pill} transition={{ duration: reduce ? 0 : 0.25 }} />}
            <span className={styles.stepText}>{STEP_LABEL[s]}</span>
          </button>
        ))}
      </div>
      <div className={styles.scroller}>
        <table className={styles.table}>
          <thead>
            <tr>
              {file.headers.map((h, i) => {
                const c = cells[i] as Cell;
                return (
                  <th key={h} scope="col" className={styles.head} data-verdict={c.verdict}>
                    <span className={styles.header}>{h}</span>
                    <motion.div
                      key={`${step}-${h}`}
                      className={styles.note}
                      initial={reduce ? false : { opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.32, delay: reduce ? 0 : i * 0.05, ease: [0.2, 0.7, 0.1, 1] }}
                    >
                      {c.field ? (
                        <span className={styles.read}>
                          {c.fields.map(fieldName).join(" and ")}
                          {c.unit && <span className={styles.unit}> in {c.unit}</span>}
                        </span>
                      ) : (
                        <span className={styles.unused}>not used</span>
                      )}
                      {c.codes.length > 0 && (
                        <span className={styles.codes}>
                          {c.codes.map(([code, mode]) => (
                            <span key={code}>
                              {code} means {modeName(mode)}
                            </span>
                          ))}
                        </span>
                      )}
                      {c.verdict === "fail" && c.reasons.map((r) => <span key={r} className={styles.reason}>Code: {r}</span>)}
                      {c.verdict === "person" && <span className={styles.person}>Settled by a person</span>}
                      {c.verdict === "ok" && c.field && <span className={styles.ok}>Code accepts</span>}
                    </motion.div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {file.sample.map((row, r) => (
              <tr key={r}>
                {row.map((v, i) => (
                  <td key={i} className={styles.cell} data-verdict={(cells[i] as Cell).verdict}>
                    {v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.foot}>
        First {file.sample.length} of {file.rows} rows. Checks compare what a reading implies with public reference data: distances against the
        great-circle distance of each lane, weights against what each mode can carry, modes against the ports, airports and terminals on each lane.
      </p>
    </section>
  );
}
