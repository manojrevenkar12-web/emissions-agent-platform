import type { Split } from "../../shared/data/report";
import { num } from "../../shared/format";
import { EmptyState } from "../../shared/ui/States";
import { Section } from "../../shared/ui/Section";
import t from "../../shared/ui/table.module.css";
import styles from "./governance.module.css";

const KIND: Record<string, string> = {
  total: "Answered from the tool",
  lane: "Answered from the tool",
  primary_share: "Answered from the tool",
  cross_tenant: "Refused: the tenant comes from the caller's key",
  injected: "Answered; the write it asked for was denied",
};

export function Governance({ split }: { split: Split }) {
  const s = split.samples;
  const d = split.designs;
  const p = d.platform ?? {};
  return (
    <Section
      id="governance"
      title="Who may do what, and the record of it"
      intro={`Agents act as service principals with narrow roles. Across these seeds the platform denied ${num(p.write_attempts_blocked as number, 0)} write attempts from questions, kept ${num(p.cross_tenant_leaks as number, 0)} answers about other tenants, and sent ${num(p.emails_unapproved as number, 0)} carrier emails without a person.`}
    >
      <div className={styles.grid}>
        <div className={styles.panel}>
          <h3 className={styles.h3}>Questions from customers</h3>
          {s.answers.length === 0 ? (
            <EmptyState title="No sample questions" />
          ) : (
            <ul className={styles.qa}>
              {s.answers.map((a) => (
                <li key={a.kind} className={styles.q} data-kind={a.kind}>
                  <p className={styles.question}>{a.question}</p>
                  <p className={styles.answer}>{a.answer}</p>
                  <p className={styles.how}>{KIND[a.kind] ?? a.kind}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className={styles.panel}>
          <h3 className={styles.h3}>A carrier reply with an instruction in it</h3>
          {s.injected_reply ? (
            <>
              <pre className={styles.reply}>
                {s.injected_reply.text}
                {"\n…\n\n"}
                <mark className={styles.mark}>{s.injected_reply.instruction}</mark>
              </pre>
              <p className={styles.how}>The reply is fenced as data, flagged by the instruction check and sent to a person. Code would refuse zero or halved fuel anyway: implied fuel per tonne-km must fall inside 0.45 to 2.2 times the default.</p>
            </>
          ) : (
            <EmptyState title="No injected reply in this seed" />
          )}
          <h3 className={styles.h3}>The audit chain</h3>
          <p className={styles.how}>
            {s.audit.count.toLocaleString("en")} entries, chain {s.audit.verified ? "verified" : "broken"}. Each entry commits to the one before it.
          </p>
          <ol className={styles.chain}>
            {s.audit.entries.slice(0, 5).map((e) => (
              <li key={e.n}>
                <span className={styles.hash}>{e.hash.slice(0, 10)}</span> {e.actor} {e.action.replace(/_/g, " ")}: {e.outcome}
              </li>
            ))}
          </ol>
        </div>
      </div>
      <div className={t.scroller}>
        <table className={t.table}>
          <thead>
            <tr>
              <th scope="col">Release gate ({split.split === "dev" ? "development seeds" : "held-out seeds"})</th>
              <th scope="col">Value</th>
              <th scope="col">Limit</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {split.gates.platform.map((g) => (
              <tr key={g.gate}>
                <th scope="row">{g.gate}</th>
                <td>{num(g.value, g.value < 1 && g.value > 0 ? 3 : 1)}</td>
                <td className={t.muted}>
                  {g.kind === "min" ? "at least" : "at most"} {g.limit}
                </td>
                <td className={g.pass ? t.good : t.bad}>{g.pass ? "Pass" : "Fail"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
