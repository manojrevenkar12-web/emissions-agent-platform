import type { Split } from "../../shared/data/report";
import { eur, int, num, pct } from "../../shared/format";
import { Section } from "../../shared/ui/Section";
import t from "../../shared/ui/table.module.css";

const COLS = ["status_quo", "model_alone", "platform"] as const;
const HEAD: Record<(typeof COLS)[number], string> = { status_quo: "People with spreadsheets", model_alone: "One agent, all tools", platform: "The platform" };

type Row = [string, string, (x: number | null) => string, "low" | "high"];
const ROWS: Row[] = [
  ["Monthly total off by, median tenant-month", "tenant_month_error_median", (x) => pct(x), "low"],
  ["Monthly total off by, 95th percentile", "tenant_month_error_p95", (x) => pct(x), "low"],
  ["Shipments with a unit or column error, per 10,000", "gross_row_errors_per_10k", (x) => num(x), "low"],
  ["Road emissions resting on measured fuel", "primary_share_road", (x) => pct(x), "high"],
  ["Rows labelled primary that were never measured", "false_primary_rows", int, "low"],
  ["Cleaner-carrier pairs ranked the right way round", "carrier_ranking_concordance", (x) => pct(x, 0), "high"],
  ["Analyst minutes per 1,000 shipments", "analyst_minutes_per_1k", (x) => num(x), "low"],
  ["Hours until a file is report-ready, 90th percentile", "turnaround_h_p90", (x) => num(x), "low"],
  ["Model cost per 1,000 shipments", "llm_cost_eur_per_1k", eur, "low"],
  ["Carrier emails sent without a person", "emails_unapproved", int, "low"],
  ["Answers with a wrong number, per 100", "answers_wrong_number_per_100", (x) => num(x), "low"],
  ["Answers that showed another tenant's data", "cross_tenant_leaks", int, "low"],
];

export function Results({ split }: { split: Split }) {
  const d = split.designs;
  const w = split.world;
  return (
    <Section
      id="results"
      title="What a quarter of carrier files turns into"
      intro={
        <>
          {w.tenants} shipper tenants, {w.carriers} carriers, {int(w.files)} weekly files, {int(w.shipments)} shipments and {int(w.questions)} customer
          questions over {split.seeds.length} seeds. All three designs meet the same files, the same carrier replies and the same coin flips. With default
          factors alone, even a perfect reading stays {pct(split.floor.median)} off at the median: only measured fuel moves that.
        </>
      }
    >
      <div className={t.scroller}>
        <table className={t.table}>
          <thead>
            <tr>
              <th scope="col">Per quarter, all seeds</th>
              {COLS.map((c) => (
                <th key={c} scope="col" className={c === "platform" ? t.platform : undefined}>
                  {HEAD[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([label, key, fmt]) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                {COLS.map((c) => (
                  <td key={c} className={c === "platform" ? `${t.platform} ${t.strong}` : undefined}>
                    {fmt((d[c]?.[key] as number | null) ?? null)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
