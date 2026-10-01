import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Users, Tag, GraduationCap, List, LogOut,
  BarChart3, Crown, ShieldCheck, History, Settings as SettingsIcon,
  Search, Ticket, CalendarClock,
} from "lucide-react";
import { useLogout, useMe } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import CommandPalette from "./CommandPalette";

type Entry = { to: string; label: string; icon: any; end?: boolean; adminOnly?: boolean };

// Full nav — filtered by role below.
// "staff" (ресепшен: Ольга, Арби) sees only bookings + catalog.
// "admin" (руководители: Дини + админ-аккаунт) видит всё.
const mainNavFull: Entry[] = [
  { to: "/", label: "Дашборд", icon: LayoutDashboard, end: true },
  { to: "/analytics", label: "Аналитика", icon: BarChart3 },
  { to: "/bookings", label: "Брони", icon: List },
  { to: "/trainers-schedule", label: "График тренеров", icon: CalendarClock },
];

const catalogNav: Entry[] = [
  { to: "/customers", label: "Клиенты", icon: Users },
  { to: "/catalog", label: "Услуги", icon: Tag },
  { to: "/instructors", label: "Тренеры", icon: GraduationCap },
  { to: "/memberships", label: "Абонементы", icon: Crown },
  { to: "/coupons", label: "Промокоды", icon: Ticket },
];

const adminNav: Entry[] = [
  { to: "/staff", label: "Сотрудники", icon: ShieldCheck, adminOnly: true },
  { to: "/audit", label: "Журнал", icon: History, adminOnly: true },
  { to: "/settings", label: "Настройки", icon: SettingsIcon, adminOnly: true },
];

function roleLabel(role?: string) {
  switch (role) {
    case "admin": return "Руководитель";
    case "manager": return "Менеджер";
    case "staff": return "Администратор (ресепшен)";
    case "instructor": return "Тренер";
    case "accounting": return "Касса";
    default: return role || "";
  }
}

export default function Layout() {
  const navigate = useNavigate();
  const { data: user } = useMe();
  const logout = useLogout();
  const isAdmin = user?.role === "admin";
  const isManager = isAdmin || user?.role === "manager";
  const isStaff = user?.role === "staff";
  const isInstructor = user?.role === "instructor";

  // Основное меню — у тренера Дашборд + Мои брони + Мой график;
  // у ресепшена Дашборд + Брони + График тренеров; у менеджера/админа — всё.
  const mainNav: Entry[] = isInstructor
    ? [
      { to: "/", label: "Дашборд", icon: LayoutDashboard, end: true },
      { to: "/bookings", label: "Мои брони", icon: List },
      { to: "/my-schedule", label: "Мой график", icon: CalendarClock },
    ]
    : isStaff
      ? [
        { to: "/", label: "Дашборд", icon: LayoutDashboard, end: true },
        { to: "/bookings", label: "Брони", icon: List },
        { to: "/trainers-schedule", label: "График тренеров", icon: CalendarClock },
      ]
      : mainNavFull;

  // Справочники — тренер теперь может работать с клиентами (как ресепшен).
  // Осталось read-only просмотр каталога, абонементов, промокодов.
  const catalogMenu: Entry[] = isInstructor
    ? [
      { to: "/customers", label: "Клиенты", icon: Users },
      { to: "/catalog-view", label: "Услуги", icon: Tag },
      { to: "/memberships", label: "Абонементы", icon: Crown },
      { to: "/coupons", label: "Промокоды", icon: Ticket },
    ]
    : isStaff
      ? [
        { to: "/customers", label: "Клиенты", icon: Users },
        { to: "/catalog-view", label: "Услуги", icon: Tag },
        { to: "/instructors-view", label: "Тренеры", icon: GraduationCap },
        { to: "/memberships", label: "Абонементы", icon: Crown },
        { to: "/coupons", label: "Промокоды", icon: Ticket },
      ]
      : catalogNav;
  void isManager;

  return (
    <div className="flex min-h-screen">
      <aside className="w-64 bg-brand text-white flex flex-col">
        <div className="p-5 border-b border-white/10">
          <div className="text-xl font-bold">GolfAdmin</div>
          <div className="text-sm opacity-80 mt-0.5">Крылатское</div>
        </div>

        <button
          className="mx-3 mt-3 flex items-center gap-2 text-base bg-white/10 hover:bg-white/15 rounded-lg px-3 py-2 text-white/80"
          data-testid="open-cmdk-btn"
          onClick={() => {
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
          }}
          title="Cmd/Ctrl + K"
        >
          <Search size={16} /> Поиск <kbd className="ml-auto text-xs bg-white/20 rounded px-1.5 py-0.5">⌘K</kbd>
        </button>

        <nav className="py-3 overflow-y-auto" data-testid="sidebar-nav">
          <Section label="" items={mainNav} />
          <Section label="Справочники" items={catalogMenu} />
          {isAdmin && <Section label="Администрирование" items={adminNav} />}
        </nav>

        {/* Логаут-блок сразу после разделов, чтобы у тренера и ресепшена кнопка не улетала
             в самый низ пустого сайдбара. */}
        <div className="mt-2 p-4 border-t border-white/10 text-base">
          <div className="font-medium" data-testid="current-user">{user?.name}</div>
          <div className="text-sm opacity-70 mb-3">{roleLabel(user?.role)}</div>
          <button
            className="flex items-center gap-2 text-white/80 hover:text-white transition"
            onClick={async () => {
              await logout.mutateAsync();
              navigate("/login", { replace: true });
            }}
            data-testid="logout-btn"
          >
            <LogOut size={18} /> Выйти
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
      <CommandPalette />
    </div>
  );
}

function Section({ label, items }: { label: string; items: Entry[] }) {
  return (
    <div className="mt-3">
      {label && (
        <div className="px-5 pb-1.5 text-[10px] uppercase tracking-widest text-white/50 font-semibold">
          {label}
        </div>
      )}
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 px-5 py-2.5 text-base transition",
              isActive
                ? "bg-white/15 text-white border-l-2 border-brand-gold"
                : "text-white/80 hover:bg-white/10 hover:text-white"
            )
          }
        >
          <Icon size={18} />
          {label}
        </NavLink>
      ))}
    </div>
  );
}
