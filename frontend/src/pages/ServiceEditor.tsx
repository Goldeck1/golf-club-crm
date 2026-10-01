import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Edit2, Power, X } from "lucide-react";
import { api, type Service } from "@/lib/api";
import { formatRub } from "@/lib/utils";
import TagInput from "@/components/TagInput";

const CATEGORIES = [
  ["range", "Range"], ["driving_range", "Драйвинг-рэндж"], ["academic_holes", "Академические лунки"],
  ["lesson", "Тренировка"], ["lesson_trial", "Пробная"], ["lesson_kids", "Детская"],
  ["simulator", "Симулятор"], ["billiard", "Бильярд"], ["massage", "Массаж"],
  ["excursion", "Экскурсия"], ["event", "Событие"],
];

export default function ServiceEditor() {
  const qc = useQueryClient();
  const { data: services } = useQuery({ queryKey: ["services-all"], queryFn: api.services });
  const { data: tagsData } = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const [editing, setEditing] = useState<Partial<Service> | null>(null);

  const toggle = useMutation({
    mutationFn: (id: number) => api.toggleService(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["services-all"] }),
  });

  const save = useMutation({
    mutationFn: async (svc: Partial<Service>) => {
      if (svc.id) return api.updateService(svc.id, svc, false);
      return api.createService({
        ...svc,
        category: svc.category || "lesson",
        sku: svc.sku || String(Date.now()),
        base_price_kopecks: svc.base_price_kopecks || 0,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services-all"] });
      qc.invalidateQueries({ queryKey: ["services"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      setEditing(null);
    },
  });

  const grouped: Record<string, Service[]> = {};
  for (const s of services || []) (grouped[s.category] ??= []).push(s);

  return (
    <div className="p-8 max-w-7xl" data-testid="service-editor-page">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-semibold">Каталог услуг</h1>
        <button
          className="btn-primary"
          onClick={() => setEditing({
            category: "lesson", name: "", sku: "", duration_min: 60,
            base_price_kopecks: 0, tags: [], active: true,
          })}
          data-testid="new-service-btn"
        >
          <Plus size={16} /> Новая услуга
        </button>
      </div>

      <div className="space-y-5">
        {Object.entries(grouped).map(([cat, list]) => (
          <div key={cat} className="card">
            <h2 className="font-semibold mb-3">
              {CATEGORIES.find(([c]) => c === cat)?.[1] || cat}
            </h2>
            <table className="w-full text-sm">
              <thead className="text-left text-stone-500">
                <tr>
                  <th className="pb-2 font-medium">Название</th>
                  <th className="pb-2 font-medium">SKU</th>
                  <th className="pb-2 font-medium">Мин</th>
                  <th className="pb-2 font-medium">Гр.</th>
                  <th className="pb-2 font-medium">Теги</th>
                  <th className="pb-2 font-medium text-right">Цена</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {list.map((s) => (
                  <tr key={s.id} className="border-t border-stone-100" data-testid={`service-row-${s.id}`}>
                    <td className="py-2 font-medium">{s.name}{!s.active && <span className="text-stone-400 ml-2 text-xs">(выкл)</span>}</td>
                    <td className="text-stone-500 font-mono text-xs">{s.sku}</td>
                    <td>{s.duration_min}</td>
                    <td>{s.group_size ?? "—"}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {(s.tags || []).map((t) => (
                          <span key={t} className="text-[10px] bg-brand/10 text-brand px-1.5 py-0.5 rounded">
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="text-right font-semibold">{formatRub(s.base_price_kopecks)}</td>
                    <td className="text-right whitespace-nowrap">
                      <button className="text-stone-500 hover:text-brand mr-1" onClick={() => setEditing(s)}>
                        <Edit2 size={14} />
                      </button>
                      <button
                        className={s.active ? "text-stone-400 hover:text-amber-600" : "text-emerald-600 hover:text-emerald-800"}
                        onClick={() => toggle.mutate(s.id)}
                        title={s.active ? "Выключить" : "Включить"}
                      >
                        <Power size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <form
            className="bg-white rounded-2xl p-6 w-full max-w-lg max-h-[90vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => { e.preventDefault(); save.mutate(editing); }}
            data-testid="service-edit-modal"
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-lg">{editing.id ? "Правка услуги" : "Новая услуга"}</h2>
              <button type="button" onClick={() => setEditing(null)}><X size={20} /></button>
            </div>

            <label className="label">Название *</label>
            <input
              className="input" required value={editing.name || ""}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              data-testid="svc-input-name"
            />

            <div className="grid grid-cols-2 gap-3 mt-3">
              <div>
                <label className="label">Категория</label>
                <select
                  className="input" value={editing.category}
                  onChange={(e) => setEditing({ ...editing, category: e.target.value })}
                >
                  {CATEGORIES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="label">SKU *</label>
                <input
                  className="input font-mono text-xs" required value={editing.sku || ""}
                  onChange={(e) => setEditing({ ...editing, sku: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3 mt-3">
              <div>
                <label className="label">Длительность, мин</label>
                <input
                  type="number" min={5} step={5} className="input"
                  value={editing.duration_min ?? 60}
                  onChange={(e) => setEditing({ ...editing, duration_min: Number(e.target.value) })}
                />
              </div>
              <div>
                <label className="label">Цена, ₽ *</label>
                <input
                  type="number" min={0} required className="input"
                  value={Math.round((editing.base_price_kopecks || 0) / 100)}
                  onChange={(e) => setEditing({ ...editing, base_price_kopecks: Number(e.target.value) * 100 })}
                  data-testid="svc-input-price"
                />
              </div>
              <div>
                <label className="label" title="Сколько человек может посещать услугу одновременно. 1 = персональная, 2-4 = групповая, пусто = без лимита">
                  Макс. гостей ⓘ
                </label>
                <input
                  type="number" min={0} className="input"
                  placeholder="без лимита"
                  value={editing.group_size ?? ""}
                  onChange={(e) => setEditing({ ...editing, group_size: e.target.value ? Number(e.target.value) : undefined })}
                />
              </div>
            </div>

            <div className="mt-3">
              <label className="label">Теги</label>
              <TagInput
                value={editing.tags || []}
                onChange={(tags) => setEditing({ ...editing, tags })}
                suggestions={tagsData?.all || []}
                placeholder="напр. premium, vip, weekend"
              />
            </div>

            <div className="grid grid-cols-3 gap-3 mt-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!editing.is_trial}
                       onChange={(e) => setEditing({ ...editing, is_trial: e.target.checked })} />
                Пробная
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!editing.is_kids}
                       onChange={(e) => setEditing({ ...editing, is_kids: e.target.checked })} />
                Детская
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!editing.requires_instructor}
                       onChange={(e) => setEditing({ ...editing, requires_instructor: e.target.checked })} />
                Нужен тренер
              </label>
            </div>

            <label className="label mt-3">Описание</label>
            <textarea
              className="input" rows={2}
              value={editing.description || ""}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
            />

            {save.isError && (
              <div className="bg-red-50 text-red-700 text-sm p-2 rounded mt-3">
                {(save.error as any)?.message || "Ошибка"}
              </div>
            )}

            <div className="flex gap-2 mt-5">
              <button type="button" className="btn-ghost flex-1" onClick={() => setEditing(null)}>Отмена</button>
              <button className="btn-primary flex-1" disabled={save.isPending} data-testid="svc-submit">
                {save.isPending ? "…" : "Сохранить"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
