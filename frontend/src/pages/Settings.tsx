import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Save, Database, Trash } from "lucide-react";

export default function Settings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (data) {
      const initial: Record<string, string> = {};
      for (const s of data) initial[s.key] = s.value;
      setValues(initial);
    }
  }, [data]);

  const save = useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) => api.updateSetting(key, value),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  const seed = useMutation({
    mutationFn: () => api.seedDemo(120),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["bookings-all"] });
      alert("Демо-данные созданы! Открой Аналитику чтобы увидеть заполненные графики.");
    },
  });

  const wipe = useMutation({
    mutationFn: () => api.wipeDemo(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analytics"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      qc.invalidateQueries({ queryKey: ["bookings-all"] });
    },
  });

  const resetPrice = useMutation({
    mutationFn: () => api.resetServicesFromPrice(),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["services"] });
      qc.invalidateQueries({ queryKey: ["services-all"] });
      alert(`Каталог сброшен: ${r.total} услуг из прайса (${r.created} новых).`);
    },
  });

  return (
    <div className="p-8 max-w-3xl" data-testid="settings-page">
      <h1 className="text-2xl font-semibold mb-6">Настройки клуба</h1>

      <div className="card">
        <h2 className="font-semibold mb-4">Сезон</h2>
        <p className="text-sm text-stone-500 mb-3">
          Auto — сезон определяется по месяцу (май–сентябрь = summer). Можно зафиксировать вручную.
        </p>
        <div className="flex gap-2">
          {["auto", "summer", "winter"].map((v) => (
            <button
              key={v}
              className={
                "px-4 py-2 rounded-lg border transition " +
                (values["season_mode"] === v
                  ? "bg-brand text-white border-brand"
                  : "bg-white border-stone-300 hover:bg-stone-50")
              }
              onClick={() => {
                setValues({ ...values, season_mode: v });
                save.mutate({ key: "season_mode", value: v });
              }}
              data-testid={`season-${v}`}
            >
              {v === "auto" ? "Авто" : v === "summer" ? "Лето" : "Зима"}
            </button>
          ))}
        </div>
      </div>

      <div className="card mt-4">
        <h2 className="font-semibold mb-3">Демо-данные</h2>
        <p className="text-sm text-stone-500 mb-3">
          Сгенерировать реалистичный поток броней за последние 30 дней (чтобы Аналитика ожила).
          Использует существующие услуги/ресурсы/тренеров. Отмечает демо-брони комментарием <code>(demo)</code>,
          их потом можно снести одной кнопкой.
        </p>
        <div className="flex gap-2">
          <button
            className="btn-primary"
            onClick={() => seed.mutate()}
            disabled={seed.isPending}
            data-testid="seed-demo-btn"
          >
            <Database size={14} /> {seed.isPending ? "…" : "Сгенерировать 120 броней"}
          </button>
          <button
            className="btn-ghost text-red-600"
            onClick={() => {
              if (confirm("Удалить ВСЕ демо-брони (те что с comment='(demo)')?")) wipe.mutate();
            }}
            disabled={wipe.isPending}
          >
            <Trash size={14} /> Стереть демо
          </button>
        </div>
      </div>

      <div className="card mt-4">
        <h2 className="font-semibold mb-3">Каталог услуг</h2>
        <p className="text-sm text-stone-500 mb-3">
          Сбросить каталог до канонического прайса Крылатское 2026 (16 услуг: Range,
          Драйвинг-рэндж, Академические лунки, пробные/взрослые/детские тренировки 1–4 гостя).
          Услуги, на которые есть активные брони, переведутся в <i>неактивные</i>, остальные удалятся.
        </p>
        <button
          className="btn-primary"
          onClick={() => {
            if (confirm("Сбросить каталог до прайса? Все нестандартные услуги будут удалены или деактивированы.")) {
              resetPrice.mutate();
            }
          }}
          disabled={resetPrice.isPending}
        >
          {resetPrice.isPending ? "…" : "Сбросить по прайсу"}
        </button>
      </div>

      <div className="card mt-4">
        <h2 className="font-semibold mb-4">Сырой список настроек</h2>
        <table className="w-full text-sm">
          <thead className="text-left text-stone-500">
            <tr>
              <th className="pb-2 font-medium">Ключ</th>
              <th className="pb-2 font-medium">Значение</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.map((s) => (
              <tr key={s.key} className="border-t border-stone-100">
                <td className="py-2 font-mono text-xs">{s.key}</td>
                <td className="py-2">
                  <input
                    className="input"
                    value={values[s.key] ?? ""}
                    onChange={(e) => setValues({ ...values, [s.key]: e.target.value })}
                  />
                </td>
                <td className="py-2 text-right">
                  <button
                    className="btn-ghost text-sm"
                    onClick={() => save.mutate({ key: s.key, value: values[s.key] })}
                    disabled={save.isPending}
                  >
                    <Save size={14} /> Сохранить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
