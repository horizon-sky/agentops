"use client";

import { useCallback, useEffect, useState } from "react";
import EvalReportView from "@/components/EvalReportView";
import { fetchEvalReport } from "@/lib/api";
import type { EvalReport } from "@/lib/types";

export default function EvalDashboard() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setReport(await fetchEvalReport());
    } catch {
      setError("评测报告读取失败，请检查服务连接后重试。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return <EvalReportView report={report} loading={loading} error={error} onReload={load} />;
}
