import { AlertTriangle, CheckCircle2, Clock, ShieldAlert, Info } from "lucide-react";

type Tone = "danger" | "warning" | "success" | "neutral" | "info";

const TONES: Record<Tone, string> = {
  danger: "bg-red-50 text-red-700 ring-red-200",
  warning: "bg-amber-50 text-amber-700 ring-amber-200",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  neutral: "bg-slate-100 text-slate-600 ring-slate-200",
  info: "bg-sky-50 text-sky-700 ring-sky-200",
};

export function toneForSeverity(severity: string): Tone {
  switch (severity?.toUpperCase()) {
    case "CRITICAL":
    case "HIGH":
      return "danger";
    case "MEDIUM":
      return "warning";
    case "LOW":
      return "info";
    case "INFO":
      return "neutral";
    default:
      return "neutral";
  }
}

function Icon({ tone }: { tone: Tone }) {
  const cls = "h-3.5 w-3.5";
  switch (tone) {
    case "danger":
      return <ShieldAlert className={cls} />;
    case "warning":
      return <AlertTriangle className={cls} />;
    case "success":
      return <CheckCircle2 className={cls} />;
    case "info":
      return <Info className={cls} />;
    default:
      return <Clock className={cls} />;
  }
}

export default function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${TONES[tone]}`}
    >
      <Icon tone={tone} />
      {label}
    </span>
  );
}
