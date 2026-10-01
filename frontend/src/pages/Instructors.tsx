import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function Instructors() {
  const { data } = useQuery({ queryKey: ["instructors"], queryFn: api.instructors });

  return (
    <div className="p-8 max-w-7xl" data-testid="instructors-page">
      <h1 className="text-2xl font-semibold mb-6">Тренеры</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.map((i) => (
          <div key={i.id} className="card" data-testid={`instructor-${i.id}`}>
            <div className="flex items-start gap-3">
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center text-white font-bold"
                style={{ background: i.color }}
              >
                {i.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{i.name}</div>
                <div className="text-sm text-stone-500">{i.specialization}</div>
                {i.phone && <div className="text-xs text-stone-400 mt-0.5 font-mono">{i.phone}</div>}
              </div>
            </div>
            {i.bio && <p className="text-sm text-stone-600 mt-3 leading-relaxed">{i.bio}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}
