"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import type { DashboardData, Incident, IncidentCluster } from "@/lib/dashboard-data";

type Props = {
  data: DashboardData;
};

const reveal = {
  // Keep server-rendered content visible if client JS fails to load.
  hidden: { opacity: 1, y: 0 },
  show: { opacity: 1, y: 0 },
};

function cleanStatus(status?: string): string {
  return (status || "Информация").replace("🚨 Статус: ", "").trim();
}

function cleanLocation(location?: string): string {
  return (location || "Не е посочена").replace("📍 Локация: ", "").trim();
}

function cleanHeadline(headline?: string): string {
  return (headline || "Няма заглавие").replace("📰 ", "").trim();
}

function toPrettyDate(iso?: string): string {
  if (!iso) return "n/a";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "n/a";
  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function computeOverview(data: DashboardData) {
  const incidents = data.incidents || [];
  const truckStats = data.truck_stats || [];
  const latestTruck = truckStats[truckStats.length - 1];
  const prevTruck = truckStats[truckStats.length - 2];
  const trBorderCheckpoints = ["Капитан Андреево", "Лесово"];

  const criticalCount = incidents.filter(
    (i) => cleanStatus(i.analysis?.status) === "Критично",
  ).length;

  const entryFlow = trBorderCheckpoints.reduce(
    (sum, cp) => sum + (latestTruck?.checkpoints?.[cp]?.in || 0),
    0,
  );
  const exitFlow = trBorderCheckpoints.reduce(
    (sum, cp) => sum + (latestTruck?.checkpoints?.[cp]?.out || 0),
    0,
  );
  const totalTraffic = entryFlow + exitFlow;
  const prevTotal = trBorderCheckpoints.reduce(
    (sum, cp) => sum + (prevTruck?.checkpoints?.[cp]?.in || 0) + (prevTruck?.checkpoints?.[cp]?.out || 0),
    0,
  );
  const trafficDelta = totalTraffic - prevTotal;

  return {
    incidentCount: incidents.length,
    criticalCount,
    entryFlow,
    exitFlow,
    totalTraffic,
    trafficDelta,
    latestDate: latestTruck?.date || "n/a",
  };
}

function hotspotLocations(incidents: Incident[]) {
  const normalizeHotspot = (rawLocation: string) => {
    const normalized = rawLocation.toLowerCase();

    // Canonicalize the highest-priority checkpoint names across BG/TR variants.
    if (
      normalized.includes("капитан андреево") ||
      normalized.includes("kapitan andreevo") ||
      normalized.includes("капъкуле") ||
      normalized.includes("kapıkule") ||
      normalized.includes("kapikule")
    ) {
      return "ГКПП Капитан Андреево / Капъкуле (TR)";
    }
    if (
      normalized.includes("лесово") ||
      normalized.includes("hamzabeyli") ||
      normalized.includes("хамзабейли")
    ) {
      return "ГКПП Лесово / Хамзабейли (TR)";
    }
    if (normalized.includes("малко търново") || normalized.includes("malko tarnovo")) {
      return "ГКПП Малко Търново";
    }
    if (normalized === "българо-турска граница") {
      return "Българо-турска граница (неуточнен точен ГКПП)";
    }
    return rawLocation;
  };

  const hotspotPriority = (location: string) => {
    if (location === "ГКПП Капитан Андреево / Капъкуле (TR)") return 1;
    if (location === "ГКПП Лесово / Хамзабейли (TR)") return 2;
    if (location === "ГКПП Малко Търново") return 3;
    if (location === "Българо-турска граница (неуточнен точен ГКПП)") return 90;
    return 50;
  };

  const counts: Record<string, number> = {};
  incidents.forEach((incident) => {
    const location = normalizeHotspot(cleanLocation(incident.analysis?.location));
    counts[location] = (counts[location] || 0) + 1;
  });

  return Object.entries(counts)
    .sort((a, b) => {
      const pDiff = hotspotPriority(a[0]) - hotspotPriority(b[0]);
      if (pDiff !== 0) return pDiff;
      return b[1] - a[1];
    })
    .slice(0, 4);
}

function sourceDomains(incidents: Incident[]) {
  const counts: Record<string, number> = {};
  incidents.forEach((incident) => {
    (incident.links || []).forEach((link) => {
      const domain = (link.domain || "unknown").trim();
      counts[domain] = (counts[domain] || 0) + 1;
    });
  });
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
}

function sourceDomainsFromClusters(clusters: IncidentCluster[]) {
  const counts: Record<string, number> = {};
  clusters.forEach((cluster) => {
    (cluster.sources || []).forEach((domain) => {
      const key = (domain || "unknown").trim();
      counts[key] = (counts[key] || 0) + 1;
    });
  });
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
}

export default function DashboardView({ data }: Props) {
  const [activeCluster, setActiveCluster] = useState<IncidentCluster | null>(null);
  const overview = computeOverview(data);
  const clusters = (data.incident_clusters || []).slice(0, 8);
  const hotspots = hotspotLocations(data.incidents || []);
  const domains = clusters.length
    ? sourceDomainsFromClusters(clusters)
    : sourceDomains(data.incidents || []);
  const trucks = data.truck_stats || [];

  return (
    <main className="h-screen overflow-y-auto">
      <section className="section-shell section-compact">
        <motion.div
          initial="hidden"
          animate="show"
          variants={reveal}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="max-w-6xl mx-auto w-full"
        >
          <p className="text-xs uppercase tracking-[0.22em] text-white/55">
            Border Intelligence Platform
          </p>
          <h1 className="text-5xl md:text-7xl font-semibold mt-4 leading-[1.02] tracking-tight">
            OSINT Command
            <br />
            for the Bulgarian-Turkish border.
          </h1>
          <p className="text-white/70 text-base md:text-lg mt-6 max-w-3xl">
            Premium monitoring surface blending product-grade design with live
            security intelligence. Built for rapid assessment and decision
            support.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <div className="glass-card">
              <p className="label">Last Updated</p>
              <p className="value">{toPrettyDate(data.last_updated)}</p>
            </div>
            <div className="glass-card">
              <p className="label">Latest Traffic Date</p>
              <p className="value">{overview.latestDate}</p>
            </div>
          </div>
        </motion.div>
      </section>

      <section className="section-shell section-compact">
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.3 }}
          variants={reveal}
          transition={{ duration: 0.65 }}
          className="max-w-6xl mx-auto w-full"
        >
          <h2 className="section-title">Executive Snapshot</h2>
          <p className="section-copy">
            High-level intelligence indicators designed for first-glance
            situational awareness.
          </p>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
            <div className="glass-card">
              <p className="label">Tracked Incidents</p>
              <p className="value">{overview.incidentCount}</p>
            </div>
            <div className="glass-card">
              <p className="label">Critical Incidents</p>
              <p className="value text-rose-300">{overview.criticalCount}</p>
            </div>
            <div className="glass-card">
              <p className="label">TR Border Entry (to BG)</p>
              <p className="value text-emerald-300">
                {overview.entryFlow.toLocaleString()}
              </p>
            </div>
            <div className="glass-card">
              <p className="label">TR Border Exit (from BG)</p>
              <p className="value text-sky-300">
                {overview.exitFlow.toLocaleString()}
              </p>
            </div>
            <div className="glass-card">
              <p className="label">TR Border Total Flow</p>
              <p className="value">{overview.totalTraffic.toLocaleString()}</p>
            </div>
            <div className="glass-card">
              <p className="label">Total Delta</p>
              <p
                className={`value ${
                  overview.trafficDelta >= 0 ? "text-emerald-300" : "text-amber-200"
                }`}
              >
                {overview.trafficDelta >= 0 ? "+" : ""}
                {overview.trafficDelta.toLocaleString()}
              </p>
            </div>
          </div>
          <h2 className="section-title mt-14">Truck Pressure Analysis</h2>
          <p className="section-copy">
            Comparative flow by checkpoint from the latest reporting days.
          </p>
          <div className="grid lg:grid-cols-2 gap-4 mt-8">
            {["Капитан Андреево", "Лесово"].map((cp) => {
              const latestIn = trucks[trucks.length - 1]?.checkpoints?.[cp]?.in || 0;
              const latestOut = trucks[trucks.length - 1]?.checkpoints?.[cp]?.out || 0;
              const previousIn = trucks[trucks.length - 2]?.checkpoints?.[cp]?.in || 0;
              const previousOut = trucks[trucks.length - 2]?.checkpoints?.[cp]?.out || 0;
              const totalLatest = latestIn + latestOut;
              const totalPrevious = previousIn + previousOut;
              const delta = totalLatest - totalPrevious;
              const entryPct = totalLatest > 0 ? Math.round((latestIn / totalLatest) * 100) : 0;
              const exitPct = totalLatest > 0 ? 100 - entryPct : 0;
              return (
                <div key={cp} className="glass-card">
                  <p className="label">{cp}</p>
                  <p className="value mt-2">{totalLatest.toLocaleString()}</p>
                  <div className="mt-4 space-y-3">
                    <div>
                      <div className="flex justify-between text-xs text-white/75 mb-1">
                        <span>Entry to Bulgaria</span>
                        <span>{latestIn.toLocaleString()}</span>
                      </div>
                      <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-emerald-300/80"
                          style={{ width: `${entryPct}%` }}
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-xs text-white/75 mb-1">
                        <span>Exit from Bulgaria</span>
                        <span>{latestOut.toLocaleString()}</span>
                      </div>
                      <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-sky-300/80"
                          style={{ width: `${exitPct}%` }}
                        />
                      </div>
                    </div>
                  </div>
                  <p
                    className={`text-sm mt-4 ${
                      delta >= 0 ? "text-emerald-300" : "text-amber-200"
                    }`}
                  >
                    {delta >= 0 ? "+" : ""}
                    {delta.toLocaleString()} vs previous report
                  </p>
                </div>
              );
            })}
          </div>
        </motion.div>
      </section>

      <section className="section-shell section-compact">
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.3 }}
          variants={reveal}
          transition={{ duration: 0.65 }}
          className="max-w-6xl mx-auto w-full"
        >
          <h2 className="section-title">Incident Timeline</h2>
          <p className="section-copy">
            Clustered event intelligence that merges repeated articles covering
            the same incident.
          </p>
          <div className="grid lg:grid-cols-2 gap-4 mt-8">
            {clusters.map((cluster, index) => (
              <div className="glass-card" key={`${cluster.id}-${index}`}>
                <div className="flex items-center justify-between gap-4">
                  <p className="label">{cleanLocation(cluster.analysis?.location)}</p>
                  <span className="text-xs text-white/60">
                    {toPrettyDate(cluster.last_seen_utc || cluster.first_seen_utc)}
                  </span>
                </div>
                <h3 className="text-xl leading-tight mt-4">
                  {cleanHeadline(cluster.analysis?.headline)}
                </h3>
                <p className="mt-4 text-sm text-white/75 flex flex-wrap gap-x-4 gap-y-1">
                  <span>Status: {cleanStatus(cluster.analysis?.status)}</span>
                  <span>Articles: {cluster.incident_count || 1}</span>
                  <span>Sources: {cluster.source_count || cluster.sources?.length || 0}</span>
                </p>
                <button
                  type="button"
                  onClick={() => setActiveCluster(cluster)}
                  className="mt-4 text-sm text-sky-200/90 hover:text-sky-100 transition-colors"
                >
                  View related source posts
                </button>
              </div>
            ))}
          </div>
        </motion.div>
      </section>

      <section className="section-shell section-compact pb-14">
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, amount: 0.35 }}
          variants={reveal}
          transition={{ duration: 0.65 }}
          className="max-w-6xl mx-auto w-full grid lg:grid-cols-2 gap-4"
        >
          <div className="glass-card h-full">
            <h2 className="section-title !text-3xl">Hotspot Locations</h2>
            <p className="section-copy mt-3">
              Most frequently mentioned incident geographies in the recent
              intelligence window.
            </p>
            <div className="space-y-3 mt-6">
              {hotspots.map(([location, count]) => (
                <div key={location}>
                  <div className="flex justify-between text-sm text-white/75 mb-2">
                    <span>{location}</span>
                    <span>{count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-sky-300/80 to-indigo-300/80"
                      style={{ width: `${Math.min(100, count * 12)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="glass-card h-full">
            <h2 className="section-title !text-3xl">Source Activity</h2>
            <p className="section-copy mt-3">
              Domains most represented in the current incident corpus.
            </p>
            <div className="mt-6 grid grid-cols-1 gap-2">
              {domains.map(([domain, count]) => (
                <div
                  key={domain}
                  className="rounded-2xl border border-white/15 bg-white/[0.02] px-4 py-3 flex items-center justify-between"
                >
                  <span className="text-white/85">{domain}</span>
                  <span className="text-white/55 text-sm">{count} refs</span>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </section>

      {activeCluster && (
        <div
          className="fixed inset-0 z-50 bg-black/65 backdrop-blur-sm p-4 md:p-8"
          onClick={() => setActiveCluster(null)}
          role="presentation"
        >
          <div
            className="mx-auto max-w-3xl max-h-[86vh] overflow-y-auto glass-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Related source posts"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="label">{cleanLocation(activeCluster.analysis?.location)}</p>
                <h3 className="text-2xl mt-3 leading-tight">
                  {cleanHeadline(activeCluster.analysis?.headline)}
                </h3>
                <p className="mt-3 text-sm text-white/70">
                  {activeCluster.incident_count || 1} articles •{" "}
                  {activeCluster.source_count || activeCluster.sources?.length || 0} sources
                </p>
              </div>
              <button
                type="button"
                onClick={() => setActiveCluster(null)}
                className="text-white/65 hover:text-white text-sm"
              >
                Close
              </button>
            </div>

            <div className="mt-6 space-y-2">
              {(activeCluster.articles || []).length === 0 ? (
                <p className="text-sm text-white/55">No source links available.</p>
              ) : (
                (activeCluster.articles || []).map((article, articleIdx) => (
                  <a
                    key={`${article.url}-${articleIdx}`}
                    href={article.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block rounded-xl border border-white/15 bg-white/[0.03] px-3 py-3 hover:bg-white/[0.06] transition-colors"
                  >
                    <p className="text-xs text-white/60">
                      {article.domain || "source"} • {toPrettyDate(article.first_seen_utc)}
                    </p>
                    <p className="text-sm text-white/85 mt-1">
                      {cleanHeadline(article.headline)}
                    </p>
                  </a>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
