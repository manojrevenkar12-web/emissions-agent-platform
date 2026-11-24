import { useState } from "react";
import type { Samples } from "../../shared/data/report";
import { pct } from "../../shared/format";
import { EmptyState } from "../../shared/ui/States";
import { Section } from "../../shared/ui/Section";
import styles from "./monitor.module.css";

const W = 760;
const H = 220;
const M = { l: 44, r: 16, t: 16, b: 32 };

export function Monitor({ samples, detect }: { samples: Samples; detect: (number | null)[] | undefined }) {
  const mon = samples.monitor as Samples["monitor"] & { h?: number };
  const series = mon.series;
  const deg = samples.degradation;
  const [hover, setHover] = useState<number | null>(null);
  if (!series.length) return <EmptyState title="No first reads to monitor">Every file in this run came from the mapping memory.</EmptyState>;
  const h = mon.h ?? 2.5;
  const maxDay = Math.max(...series.map((p) => p.day), deg?.end_day ?? 0) + 2;
  const maxS = Math.max(h * 1.25, ...series.map((p) => p.s));
  const x = (d: number) => M.l + (d / maxDay) * (W - M.l - M.r);
  const y = (s: number) => H - M.b - (s / maxS) * (H - M.t - M.b);
  const path = series.map((p, i) => `${i ? "L" : "M"}${x(p.day).toFixed(1)},${y(p.s).toFixed(1)}`).join(" ");
  const days = detect?.filter((v): v is number => v !== null) ?? [];
  const hp = hover === null ? null : series[hover];
  return (
    <Section
      id="monitor"
      title="When the small model got worse under the same name"
      intro={
        <>
          The world degrades the small model {deg ? `from day ${deg.start_day} to ${deg.end_day}` : "for some days"}. The platform only sees its own check
          results: a CUSUM on first reads that fail checks raises an alarm and the router sends first reads to the mid-size model for ten days.
          {days.length ? ` Detected after ${days.join(", ")} days across the seeds.` : " Not detected on these seeds."}
        </>
      }
    >
      <figure className={styles.figure}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="CUSUM statistic of first reads that fail checks, by day" className={styles.svg} onMouseLeave={() => setHover(null)}>
          {deg && <rect x={x(deg.start_day)} y={M.t} width={x(deg.end_day) - x(deg.start_day)} height={H - M.t - M.b} className={styles.window} />}
          {deg && (
            <text x={(x(deg.start_day) + x(deg.end_day)) / 2} y={H - M.b - 8} textAnchor="middle" className={styles.label}>
              Provider regression
            </text>
          )}
          {[0, h].map((v) => (
            <g key={v}>
              <line x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} className={v ? styles.threshold : styles.axis} />
              <text x={M.l - 8} y={y(v) + 4} textAnchor="end" className={styles.tick}>
                {v}
              </text>
            </g>
          ))}
          <text x={W - M.r} y={y(h) - 6} textAnchor="end" className={styles.tick}>
            Alarm threshold
          </text>
          {[0, 30, 60, 90].filter((d) => d < maxDay).map((d) => (
            <text key={d} x={x(d)} y={H - 10} textAnchor="middle" className={styles.tick}>
              day {d}
            </text>
          ))}
          <path d={path} className={styles.line} />
          {mon.alarms.map((a) => (
            <g key={a}>
              <line x1={x(a)} x2={x(a)} y1={M.t} y2={H - M.b} className={styles.alarm} />
              <text x={x(a) + 4} y={M.t + 12} className={styles.alarmText}>
                alarm, day {a}
              </text>
            </g>
          ))}
          {series.map((p, i) => (
            <rect key={p.day} x={x(p.day) - 4} y={M.t} width={8} height={H - M.t - M.b} fill="transparent" onMouseEnter={() => setHover(i)} />
          ))}
          {hp && <circle cx={x(hp.day)} cy={y(hp.s)} r={4} className={styles.dot} />}
        </svg>
        <figcaption className={styles.caption} aria-live="polite">
          {hp ? `Day ${hp.day}: ${hp.n} first reads, ${pct(hp.rate, 0)} failed checks, statistic ${hp.s.toFixed(2)}` : "Hover a day for its first reads."}
        </figcaption>
      </figure>
    </Section>
  );
}
