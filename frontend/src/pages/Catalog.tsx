import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatRub } from "@/lib/utils";

const CATEGORIES: Record<string, string> = {
  driving_range: "Драйвинг-рэндж",
  academic_holes: "Академические лунки",
  lesson_trial: "Пробные тренировки",
  lesson: "Тренировки",
  lesson_kids: "Детские тренировки",
};

const CATEGORY_ORDER = [
  "driving_range",
  "academic_holes",
  "lesson_trial",
  "lesson",
  "lesson_kids",
];

export default function Catalog() {
  const { data } = useQuery({ queryKey: ["services"], queryFn: api.services });

  const grouped = (data || []).reduce<Record<string, typeof data>>((acc, s) => {
    (acc[s.category] ??= []).push(s);
    return acc;
  }, {} as any);

  const orderedCats = [
    ...CATEGORY_ORDER.filter((c) => grouped[c]?.length),
    ...Object.keys(grouped).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  return (
    <div className="p-8 max-w-7xl" data-testid="catalog-page">
      <h1 className="text-3xl font-semibold mb-6">Каталог услуг</h1>
      <div className="space-y-6">
        {orderedCats.map((cat) => (
          <div key={cat} className="card">
            <h2 className="font-semibold mb-3 text-stone-800 text-lg">{CATEGORIES[cat] ?? cat}</h2>
            <table className="w-full text-base">
              <thead className="text-left text-stone-500">
                <tr>
                  <th className="pb-2 font-medium">Название</th>
                  <th className="pb-2 font-medium">SKU</th>
                  <th className="pb-2 font-medium">Длительность</th>
                  <th className="pb-2 font-medium">Гр.</th>
                  <th className="pb-2 font-medium text-right">Цена</th>
                </tr>
              </thead>
              <tbody>
                {grouped[cat]!.map((s) => (
                  <tr key={s.id} className="border-t border-stone-100">
                    <td className="py-2 font-medium">{s.name}</td>
                    <td className="text-stone-500 font-mono text-sm">{s.sku}</td>
                    <td>{s.duration_min} мин</td>
                    <td>{s.group_size ?? "—"}</td>
                    <td className="text-right font-semibold">{formatRub(s.base_price_kopecks)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
