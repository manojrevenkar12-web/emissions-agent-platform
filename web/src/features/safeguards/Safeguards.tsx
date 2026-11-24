import type { Split } from "../../shared/data/report";
import { eur, int, num, pct } from "../../shared/format";
import { Section } from "../../shared/ui/Section";
import t from "../../shared/ui/table.module.css";

const WHAT: Record<string, [string, string, (x: number | null) => string]> = {
  no_checks: ["Mapping checks", "tenant_month_error_p95", (x) => pct(x)],
  no_memory: ["Carrier mapping memory", "analyst_minutes_per_1k", (x) => `${num(x)} min/1k`],
  no_router: ["Small model first, larger one on doubt", "llm_cost_eur_per_1k", (x) => `${eur(x)}/1k`],
  no_approvals: ["A person approves carrier emails", "emails_with_promises", (x) => `${int(x)} ${x === 1 ? "promise" : "promises"}`],
  no_tenant_scope: ["Tenant from the caller's key", "cross_tenant_leaks", (x) => `${int(x)} ${x === 1 ? "leak" : "leaks"}`],
  no_answer_check: ["Code checks the answer's number", "answers_wrong_number_per_100", (x) => `${num(x)} per 100`],
  no_reply_checks: ["Code checks carrier replies", "false_primary_rows", (x) => `${int(x)} ${x === 1 ? "row" : "rows"}`],
  no_clarification: ["Asking carriers for fuel data", "primary_share_road", (x) => pct(x)],
};

const MEANS: Record<string, string> = {
  no_checks: "monthly total off by, 95th percentile",
  no_memory: "analyst time",
  no_router: "model cost",
  no_approvals: "emails promising something nobody approved",
  no_tenant_scope: "answers with another company's data",
  no_answer_check: "answers with a wrong number",
  no_reply_checks: "rows wrongly labelled as measured",
  no_clarification: "road emissions on measured fuel",
};

export function Safeguards({ split }: { split: Split }) {
  const d = split.designs;
  const rows = split.ablations.filter((a) => a in WHAT);
  return (
    <Section id="safeguards" title="What each safeguard is worth" intro="Each row turns one safeguard off and keeps everything else, on the same luck.">
      <div className={t.scroller}>
        <table className={t.table}>
          <thead>
            <tr>
              <th scope="col">Safeguard</th>
              <th scope="col">Measured by</th>
              <th scope="col" className={t.platform}>
                With it
              </th>
              <th scope="col">Without it</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => {
              const [name, key, fmt] = WHAT[a] as [string, string, (x: number | null) => string];
              return (
                <tr key={a}>
                  <th scope="row">{name}</th>
                  <td className={t.muted}>{MEANS[a]}</td>
                  <td className={`${t.platform} ${t.strong}`}>{fmt((d.platform?.[key] as number | null) ?? null)}</td>
                  <td className={t.bad}>{fmt((d[a]?.[key] as number | null) ?? null)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
