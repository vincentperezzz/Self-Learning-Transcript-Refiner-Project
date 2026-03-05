import { useEffect, useState } from "react";
import { healthCheck } from "../api";

export default function StatusBar() {
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    healthCheck()
      .then(() => setOk(true))
      .catch(() => setOk(false));
  }, []);

  return (
    <div className="flex items-center gap-2 text-xs text-gray-500">
      <span
        className={`w-2 h-2 rounded-full ${
          ok === null
            ? "bg-gray-600"
            : ok
              ? "bg-emerald-500"
              : "bg-red-500"
        }`}
      />
      {ok === null ? "Checking..." : ok ? "Backend connected" : "Backend offline"}
    </div>
  );
}
