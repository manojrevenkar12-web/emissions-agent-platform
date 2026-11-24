import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../test/report.fixture.json";
import { App } from "./App";

function serve(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("console", () => {
  it("shows a loading state, then the carrier file with what code said about each column", async () => {
    serve(fixture);
    render(<App />);
    expect(screen.getByRole("status", { name: "Loading the report" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "A carrier file, read by agents and checked by code" })).toBeInTheDocument();
    expect(screen.getAllByText("Settled by a person").length).toBeGreaterThan(0);
  });

  it("steps back to the first read and shows the check that rejected it", async () => {
    serve(fixture);
    render(<App />);
    await userEvent.click(await screen.findByRole("tab", { name: "First read (small model)" }));
    expect(screen.getAllByText(/^Code: /).length).toBeGreaterThan(0);
  });

  it("compares the designs and the safeguards", async () => {
    serve(fixture);
    render(<App />);
    const results = await screen.findByRole("region", { name: "What a quarter of carrier files turns into" });
    expect(within(results).getByText("The platform")).toBeInTheDocument();
    const safeguards = screen.getByRole("region", { name: "What each safeguard is worth" });
    expect(within(safeguards).getByText("Mapping checks")).toBeInTheDocument();
  });

  it("explains a failed load and loads again on request", async () => {
    serve({}, false);
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("did not load");
    serve(fixture);
    await userEvent.click(screen.getByRole("button", { name: "Load again" }));
    expect(await screen.findByRole("heading", { name: "A carrier file, read by agents and checked by code" })).toBeInTheDocument();
  });

  it("says so when the report has no sample run", async () => {
    const empty = { ...fixture, dev: { ...fixture.dev, samples: {} } };
    serve(empty);
    render(<App />);
    expect(await screen.findByText("This report has no sample run")).toBeInTheDocument();
  });

  it("refuses a file that is not a report", async () => {
    serve({ nope: true });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not in the expected shape");
  });
});
