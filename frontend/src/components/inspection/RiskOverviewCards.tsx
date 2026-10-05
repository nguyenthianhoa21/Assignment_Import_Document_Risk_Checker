import { AlertOctagon, AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import type { ValidationRiskItem } from "../../types/shipment";

export default function RiskOverviewCards({ findings }: { findings: ValidationRiskItem[] }) {
  const high = findings.filter((f) => ["CRITICAL", "HIGH"].includes(f.severity.toUpperCase())).length;
  const medium = findings.filter((f) => f.severity.toUpperCase() === "MEDIUM").length;
  const low = findings.filter((f) => ["LOW", "INFO"].includes(f.severity.toUpperCase())).length;

  const cards = [
    { label: "Total risks", value: findings.length, icon: AlertOctagon, tone: "text-slate-700 bg-slate-100" },
    { label: "High / Critical", value: high, icon: ShieldAlert, tone: "text-red-700 bg-red-100" },
    { label: "Medium", value: medium, icon: AlertTriangle, tone: "text-amber-700 bg-amber-100" },
    { label: "Low / Info", value: low, icon: CheckCircle2, tone: "text-sky-700 bg-sky-100" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map(({ label, value, icon: Icon, tone }) => (
        <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className={`mb-2 inline-flex rounded-lg p-2 ${tone}`}>
            <Icon className="h-5 w-5" />
          </div>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
          <p className="text-xs text-slate-500">{label}</p>
        </div>
      ))}
    </div>
  );
}
