import type { Split } from "../../shared/data/report";
import { eur, num, pct } from "../../shared/format";
import { Section } from "../../shared/ui/Section";
import t from "../../shared/ui/table.module.css";
import styles from "./evals.module.css";

const SLICE: Record<string, string> = {
  columns: "Columns",
  units: "Units",
  mode_codes: "Mode codes",
  reply_units: "Reply units",
  reply_values: "Reply numbers",
  question_plans: "Question plans",
  injection_followed: "Red-team replies",
};

function Interval({ lo, hi, diff, limit }: { lo: number; hi: number; diff: number; limit: number }) {
  // -6 .. +6 points
  const x = (v: number) => 50 + Math.max(-6, Math.min(6, v * 100)) * (50 / 6);
  return (
    <svg viewBox="0 0 100 14" className={styles.interval} aria-label={`${(diff * 100).toFixed(1)} points, interval ${(lo * 100).toFixed(1)} to ${(hi * 100).toFixed(1)}`}>
      <line x1={x(-limit / 100)} x2={x(-limit / 100)} y1={0} y2={14} className={styles.limit} />
      <line x1={50} x2={50} y1={2} y2={12} className={styles.zero} />
      <line x1={x(lo)} x2={x(hi)} y1={7} y2={7} className={lo < -limit / 100 ? styles.badLine : styles.goodLine} />
      <circle cx={x(diff)} cy={7} r={3} className={lo < -limit / 100 ? styles.badDot : styles.goodDot} />
    </svg>
  );
}

export function EvalGate({ split }: { split: Split }) {
  const g = split.eval_gate;
  const d = split.designs;
  const limit = 2;
  return (
    <Section
      id="evals"
      title="A new model or prompt has to pass the eval gate"
      intro={`The golden set comes from separate history seeds: ${Object.entries(g.cases)
        .map(([k, v]) => `${v} ${(SLICE[k] ?? k.replace(/_/g, " ")).toLowerCase()}`)
        .join(", ")}. Each interval is the paired 95% bootstrap interval of candidate minus current; a lower end below −${limit} points blocks. Then every candidate runs in the world anyway, so the gate's verdict can be checked.`}
    >
      <div className={styles.grid}>
        {Object.entries(g.candidates).map(([name, c]) => {
          const world = d[`swap:${name}`];
          return (
            <article key={name} className={styles.card} data-verdict={c.verdict}>
              <header className={styles.cardHead}>
                <h3 className={styles.name}>{split.labels[`swap:${name}`] ?? name}</h3>
                <span className={styles.verdict}>{c.verdict === "passes" ? "Passes" : `Blocked on ${c.blocked_on.map((b) => (b === "injection_followed" ? "following injected instructions" : (SLICE[b] ?? b).toLowerCase())).join(", ")}`}</span>
              </header>
              <table className={`${t.table} ${styles.slices}`}>
                <tbody>
                  {c.slices.map((s) => (
                    <tr key={s.slice}>
                      <th scope="row">{SLICE[s.slice] ?? s.slice}</th>
                      <td>{`${s.diff >= 0 ? "+" : ""}${(s.diff * 100).toFixed(1)} pts`}</td>
                      <td className={styles.vizCell}>
                        <Interval lo={s.lo} hi={s.hi} diff={s.diff} limit={limit} />
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <th scope="row">Follows injected instructions</th>
                    <td className={c.injection_followed.pass ? undefined : t.bad}>
                      {pct(c.injection_followed.candidate)} vs {pct(c.injection_followed.current)}
                    </td>
                    <td />
                  </tr>
                </tbody>
              </table>
              {world && (
                <p className={styles.world}>
                  In the world: {num(world.gross_row_errors_per_10k as number)} unit or column errors per 10k (current {num(d.platform?.gross_row_errors_per_10k as number)}),{" "}
                  {num(world.analyst_minutes_per_1k as number)} analyst min per 1k (current {num(d.platform?.analyst_minutes_per_1k as number)}), {eur(world.llm_cost_eur_per_1k as number)} per 1k.
                </p>
              )}
            </article>
          );
        })}
      </div>
    </Section>
  );
}
