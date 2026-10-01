import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Staff as StaffType } from "@/lib/api";
import { Plus, X, Shield, Trash2 } from "lucide-react";

const ROLES = [
  { value: "admin", label: "Администратор" },
  { value: "manager", label: "Менеджер" },
  { value: "accounting", label: "Касса" },
  { value: "staff", label: "Сотрудник" },
];

export default function Staff() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["staff"], queryFn: api.staff });
  const [creating, setCreating] = useState(false);

  const create = useMutation({
    mutationFn: (body: any) => api.createStaff(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["staff"] });
      setCreating(false);
    },
  });

  const del = useMutation({
    mutationFn: (id: number) => api.deleteStaff(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["staff"] }),
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.updateStaff(id, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["staff"] }),
  });

  return (
    <div className="p-8 max-w-6xl" data-testid="staff-page">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-2xl font-semibold">Сотрудники</h1>
        <button className="btn-primary" onClick={() => setCreating(true)} data-testid="new-staff-btn">
          <Plus size={16} /> Добавить
        </button>
      </div>

      <div className="card p-0 overflow-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-stone-500 bg-stone-50 border-b border-stone-200">
            <tr>
              <th className="px-3 py-2 font-medium">Логин</th>
              <th className="px-3 py-2 font-medium">ФИО</th>
              <th className="px-3 py-2 font-medium">Роль</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Последний вход</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.map((u) => (
              <tr key={u.id} className="border-b border-stone-100" data-testid={`staff-${u.id}`}>
                <td className="px-3 py-2 font-mono">{u.username}</td>
                <td className="px-3 py-2">{u.name}</td>
                <td className="px-3 py-2">
                  <span className="text-xs bg-brand/10 text-brand px-2 py-0.5 rounded border border-brand/20">
                    <Shield size={10} className="inline mr-1" />
                    {ROLES.find((r) => r.value === u.role)?.label || u.role}
                  </span>
                </td>
                <td className="px-3 py-2 text-stone-600">{u.email || "—"}</td>
                <td className="px-3 py-2 font-mono text-xs text-stone-500">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString("ru-RU") : "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  <label className="inline-flex items-center gap-1 mr-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={u.active}
                      onChange={(e) => toggleActive.mutate({ id: u.id, active: e.target.checked })}
                    />
                    <span className="text-xs text-stone-600">активен</span>
                  </label>
                  <button
                    className="text-red-600 hover:text-red-800"
                    onClick={() => {
                      if (confirm(`Удалить сотрудника ${u.username}?`)) del.mutate(u.id);
                    }}
                    data-testid={`delete-staff-${u.id}`}
                  >
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {creating && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setCreating(false)}>
          <form
            className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="new-staff-modal"
            onSubmit={(e) => {
              e.preventDefault();
              const fd = new FormData(e.target as HTMLFormElement);
              create.mutate({
                username: fd.get("username"),
                name: fd.get("name"),
                email: fd.get("email") || "",
                role: fd.get("role"),
                password: fd.get("password"),
              });
            }}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-lg">Новый сотрудник</h2>
              <button type="button" onClick={() => setCreating(false)}>
                <X size={20} />
              </button>
            </div>
            <label className="label">Логин *</label>
            <input name="username" className="input" required autoFocus />
            <label className="label mt-3">ФИО *</label>
            <input name="name" className="input" required />
            <label className="label mt-3">Email</label>
            <input name="email" type="email" className="input" />
            <label className="label mt-3">Роль *</label>
            <select name="role" className="input" defaultValue="staff" required>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
            <label className="label mt-3">Пароль *</label>
            <input name="password" type="password" className="input" required minLength={4} />

            {create.isError && (
              <div className="mt-3 bg-red-50 text-red-700 text-sm p-2 rounded border border-red-200">
                {(create.error as any)?.message || "Ошибка"}
              </div>
            )}

            <div className="flex gap-2 mt-5">
              <button type="button" className="btn-ghost flex-1" onClick={() => setCreating(false)}>Отмена</button>
              <button className="btn-primary flex-1" disabled={create.isPending} data-testid="submit-staff">
                {create.isPending ? "…" : "Добавить"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
