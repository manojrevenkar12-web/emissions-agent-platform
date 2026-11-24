export function pct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) return "–";
  if (x >= 10) return `${Math.round(x).toLocaleString("en")}×`;
  return `${(100 * x).toFixed(digits)}%`;
}

export function num(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) return "–";
  if (Math.abs(x) >= 1000) return Math.round(x).toLocaleString("en");
  return x.toLocaleString("en", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function eur(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  return `€${x.toFixed(3)}`;
}

export function int(x: number | null | undefined): string {
  if (x === null || x === undefined) return "–";
  return Math.round(x).toLocaleString("en");
}

const FIELD: Record<string, string> = {
  shipment_id: "shipment id",
  date: "date",
  origin: "origin",
  destination: "destination",
  weight: "weight",
  distance: "distance",
  mode: "mode",
  vehicle: "vehicle",
  fuel: "fuel",
};

export function fieldName(f: string): string {
  return FIELD[f] ?? f;
}

export function modeName(m: string): string {
  return m.replace(/_/g, " ").replace("road ftl", "full truckload").replace("road ltl", "groupage").replace("road van", "van");
}
