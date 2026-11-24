import { useState } from "react";
import type { Samples, SpanJson } from "../../shared/data/report";
import { int } from "../../shared/format";
import { EmptyState } from "../../shared/ui/States";
import { Section } from "../../shared/ui/Section";
import t from "../../shared/ui/table.module.css";
import styles from "./trace.module.css";

type Kind = "model" | "code" | "person";
const KIND_LABEL: Record<Kind, string> = { model: "Model call", code: "Code", person: "Person" };
const NAMES: Record<string, string> = {
  "map.read": "First read",
  "map.second_read": "Second read",
  "map.checks": "Checks",
  "map.memory": "Memory lookup",
  "person.review_mapping": "Review of doubtful decisions",
  "person.confirm_unit": "Unit confirmed",
  "person.review_rows": "Rows outside a mode's range",
  "person.map_by_hand": "Mapped by hand",
};

function kindOf(s: SpanJson): Kind {
  if (s.model) return "model";
  if (s.name.startsWith("person.")) return "person";
  return "code";
}

function duration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60000).toFixed(1)} min`;
}

// log scale from 1 ms to 1 hour, so a 3 ms check and a 9 minute review both stay visible
const width = (ms: number) => Math.max(2, (Math.log10(Math.max(ms, 1)) / Math.log10(3.6e6)) * 100);

export function Trace({ samples }: { samples: Samples }) {
  const spans = samples.file.trace;
  const [hover, setHover] = useState<number | null>(null);
  const summary = Object.entries(samples.spans).filter(([, v]) => v.tokens_in + v.tokens_out > 0);
  return (
    <Section
      id="trace"
      title="Where the time goes on one file"
      intro="Every model call, check and person step is a span with tokens, cost and latency. The service exports the same spans over OpenTelemetry to Datadog."
    >
      {spans.length === 0 ? (
        <EmptyState title="No trace kept for this file">The study keeps traces for the first seed's platform run only.</EmptyState>
      ) : (
        <div className={styles.trace} role="list" aria-label={`Spans of file ${samples.file.file_id}`}>
          <div className={styles.legend} aria-hidden="true">
            {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
              <span key={k} className={styles.key} data-kind={k}>
                {KIND_LABEL[k]}
              </span>
            ))}
            <span className={styles.scale}>Bar length on a log scale, 1 ms to 1 hour</span>
          </div>
          {spans.map((s, i) => {
            const k = kindOf(s);
            return (
              <div key={i} role="listitem" className={styles.row} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0}>
                <span className={styles.name}>{NAMES[s.name] ?? s.name}</span>
                <span className={styles.track}>
                  <span className={styles.bar} data-kind={k} style={{ width: `${width(s.duration_ms)}%` }} />
                </span>
                <span className={styles.value}>{duration(s.duration_ms)}</span>
                {hover === i && (
                  <span className={styles.tip} role="tooltip">
                    {KIND_LABEL[k]}
                    {s.model ? `, ${s.model} model, ${int(s.tokens_in)} tokens in, ${int(s.tokens_out)} out, €${s.cost_eur.toFixed(4)}` : ""}
                    {s.status !== "ok" ? `, ${s.status}` : ""}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {summary.length > 0 && (
        <div className={t.scroller}>
          <table className={t.table}>
            <thead>
              <tr>
                <th scope="col">Model calls in the first seed</th>
                <th scope="col">Calls</th>
                <th scope="col">p50</th>
                <th scope="col">p95</th>
                <th scope="col">Tokens in</th>
                <th scope="col">Tokens out</th>
              </tr>
            </thead>
            <tbody>
              {summary.map(([name, v]) => (
                <tr key={name}>
                  <th scope="row">{name}</th>
                  <td>{int(v.count)}</td>
                  <td>{duration(v.p50_ms)}</td>
                  <td>{duration(v.p95_ms)}</td>
                  <td>{int(v.tokens_in)}</td>
                  <td>{int(v.tokens_out)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
