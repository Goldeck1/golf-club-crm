import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  X, AlertCircle, CheckCircle2, Calculator, Loader2,
  MapPin, GraduationCap, Users as UsersIcon, Clock, Ticket,
} from "lucide-react";
import {
  api,
  type BookingCategory, type TrainingType,
  type ScenarioInput, type ScenarioQuote,
} from "@/lib/api";
import { cn, formatRub } from "@/lib/utils";
import { useMe } from "@/hooks/useAuth";

type Props = {
  /** default date (YYYY-MM-DD) */
  date: string;
  /** default start time (HH:MM) */
  time?: string;
  onClose: () => void;
};

function pad(n: number) { return String(n).padStart(2, "0"); }

function composeISO(date: string, time: string) {
  return `${date}T${time}:00`;
}

function addMinutesHHMM(time: string, minutes: number) {
  const [h, m] = time.split(":").map(Number);
  const total = h * 60 + m + minutes;
  const hh = Math.floor(total / 60) % 24;
  const mm = total % 60;
  return `${pad(hh)}:${pad(mm)}`;
}

function timeToMinutes(time: string) {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

/** Extract raw 10 digits of a Russian mobile from free-form input.
 * Accepts paste like "+7 (900) 123-45-67", "8 900 ...", "79001234567".
 * Returns at most 10 digits (national part, no leading 7/8). */
function extractRuDigits(raw: string): string {
  const d = raw.replace(/\D/g, "");
  let rest = d;
  if (rest.startsWith("8")) rest = rest.slice(1);
  else if (rest.startsWith("7")) rest = rest.slice(1);
  return rest.slice(0, 10);
}

/** Formats national 10-digit part as "+7 (XXX) XXX-XX-XX" progressively. */
function formatRuPhone(digits10: string): string {
  const d = digits10;
  if (!d) return "";
  const p1 = d.slice(0, 3);
  const p2 = d.slice(3, 6);
  const p3 = d.slice(6, 8);
  const p4 = d.slice(8, 10);
  let out = "+7";
  if (p1) out += ` (${p1}${p1.length === 3 ? ")" : ""}`;
  if (p2) out += ` ${p2}`;
  if (p3) out += `-${p3}`;
  if (p4) out += `-${p4}`;
  return out;
}

export default function BookingScenarioDialog({ date, time = "10:00", onClose }: Props) {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const isInstructor = me?.role === "instructor";
  const lockedTrainerId = isInstructor ? (me?.instructor_id ?? null) : null;

  // ── form state
  const [startDate, setStartDate] = useState(date);
  const [startTime, setStartTime] = useState(time);
  const [endTime, setEndTime] = useState(() => addMinutesHHMM(time, 60));
  const [category, setCategory] = useState<BookingCategory>("range_weekday_basket");
  const [guests, setGuests] = useState(1);
  const [baskets, setBaskets] = useState(1);
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [customerQuery, setCustomerQuery] = useState("");
  const [quickName, setQuickName] = useState("");
  const [quickPhone, setQuickPhone] = useState("");
  const [showQuickCreate, setShowQuickCreate] = useState(false);
  const [comment, setComment] = useState("");
  // Тренер, создающий бронь через этот диалог, всегда делает её с собой —
  // чекбокс «с тренировкой» включён и зафиксирован.
  const [hasTraining, setHasTraining] = useState(isInstructor);
  const [trainingType, setTrainingType] = useState<TrainingType>("trial");
  const [trainerId, setTrainerId] = useState<number | null>(lockedTrainerId);
  const [couponCode, setCouponCode] = useState("");
  const [membershipId, setMembershipId] = useState<number | null>(null);

  // Если login/роль пришли позже — подстрахуемся, чтобы у тренера всегда был его id.
  useEffect(() => {
    if (isInstructor && me?.instructor_id && trainerId !== me.instructor_id) {
      setTrainerId(me.instructor_id);
      setHasTraining(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isInstructor, me?.instructor_id]);

  // ── data queries
  const { data: catalog } = useQuery({ queryKey: ["scenario-catalog"], queryFn: api.scenarioCatalog });
  const { data: instructors } = useQuery({ queryKey: ["instructors"], queryFn: api.instructors });
  const { data: customers } = useQuery({ queryKey: ["customers"], queryFn: () => api.customers() });

  // Active memberships for the selected customer (for tariff discount)
  const { data: customerMemberships } = useQuery({
    queryKey: ["customer-memberships", customerId],
    queryFn: () => (customerId ? api.customerMemberships(customerId) : Promise.resolve([])),
    enabled: !!customerId,
  });
  const activeMemberships = useMemo(
    () => (customerMemberships || []).filter((m) => m.active),
    [customerMemberships]
  );

  // Clear selected membership when the client changes — otherwise we'd send an id
  // that no longer belongs to the current customer.
  useEffect(() => { setMembershipId(null); }, [customerId]);

  const OPEN_MIN = 8 * 60;
  const CLOSE_MIN = 22 * 60;
  const durationMin = useMemo(
    () => Math.max(0, timeToMinutes(endTime) - timeToMinutes(startTime)),
    [startTime, endTime]
  );
  const startMin = timeToMinutes(startTime);
  const endMin = timeToMinutes(endTime);
  const outsideHours = startMin < OPEN_MIN || endMin > CLOSE_MIN;
  const invalidTimeRange = durationMin <= 0 || outsideHours;
  const startsAtISO = useMemo(() => composeISO(startDate, startTime), [startDate, startTime]);
  const endsAtISO = useMemo(() => composeISO(startDate, endTime), [startDate, endTime]);

  // When the user moves start — shift end to preserve current duration (or default 60).
  useEffect(() => {
    const curDur = timeToMinutes(endTime) - timeToMinutes(startTime);
    if (curDur <= 0) {
      setEndTime(addMinutesHHMM(startTime, 60));
    }
  }, [startTime]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset training type guests to ≤4 (matrix limit) — we still allow guests > 4 on range without training
  useEffect(() => {
    if (hasTraining && guests > 4) setGuests(4);
  }, [hasTraining]);

  const activeCategory = useMemo(
    () => catalog?.categories.find((c) => c.code === category),
    [catalog, category]
  );
  const usesBaskets = !!activeCategory?.basket_unit;
  const perGuest = !!activeCategory?.per_guest;

  // Reset basket count when switching away from basket-unit categories
  useEffect(() => {
    if (!usesBaskets && baskets !== 1) setBaskets(1);
  }, [usesBaskets]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── live quote
  const scenarioBody: ScenarioInput = useMemo(() => ({
    category,
    guests,
    has_training: hasTraining,
    training_type: hasTraining ? trainingType : null,
    trainer_id: hasTraining ? trainerId : null,
    starts_at: startsAtISO,
    ends_at: endsAtISO,
    customer_id: customerId,
    comment,
    baskets: usesBaskets ? baskets : 1,
    coupon_code: couponCode.trim(),
    membership_id: membershipId,
  }), [category, guests, hasTraining, trainingType, trainerId, startsAtISO, endsAtISO, customerId, comment, usesBaskets, baskets, couponCode, membershipId]);

  const quoteQ = useQuery({
    queryKey: ["scenario-quote", scenarioBody],
    queryFn: () => api.scenarioQuote(scenarioBody),
    staleTime: 0,
  });
  const quote: ScenarioQuote | undefined = quoteQ.data;

  // ── customer filter
  const filteredCustomers = useMemo(() => {
    const q = customerQuery.trim().toLowerCase();
    if (!q) return customers?.slice(0, 50) ?? [];
    return (customers || []).filter((c) =>
      c.name.toLowerCase().includes(q) || c.phone?.toLowerCase().includes(q)
    ).slice(0, 50);
  }, [customers, customerQuery]);

  const createCustomer = useMutation({
    mutationFn: () => api.createCustomer({ name: quickName.trim(), phone: quickPhone.trim() }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["customers"] });
      setCustomerId(c.id);
      setCustomerQuery(c.name);
      setShowQuickCreate(false);
      setQuickName(""); setQuickPhone("");
    },
  });

  // ── save
  const save = useMutation({
    mutationFn: () => api.createScenarioBooking(scenarioBody),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bookings-all"] });
      qc.invalidateQueries({ queryKey: ["bookings-day"] });
      qc.invalidateQueries({ queryKey: ["dash-bookings"] });
      qc.invalidateQueries({ queryKey: ["dash-sched"] });
      qc.invalidateQueries({ queryKey: ["cal-events"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      onClose();
    },
  });

  const canSave = quote?.ok && (customerId != null) && !save.isPending && !invalidTimeRange;

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-stretch justify-center p-4 overflow-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-5xl my-auto grid grid-cols-1 lg:grid-cols-[1fr_380px] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* LEFT: form */}
        <div className="p-6 overflow-auto max-h-[90vh]">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-2xl font-semibold">Новая бронь</h2>
              <p className="text-stone-500 text-sm mt-0.5">Сценарий администратора — цена и конфликты считаются автоматически.</p>
            </div>
            <button onClick={onClose} className="text-stone-400 hover:text-stone-700 p-1">
              <X size={22} />
            </button>
          </div>

          {/* 1. Дата и время */}
          <Section title="1. Дата и время" icon={Clock}>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label">Дата</label>
                <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              </div>
              <div>
                <label className="label">Начало</label>
                <input
                  type="time" min="08:00" max="22:00"
                  className={cn("input", startMin < OPEN_MIN && "border-red-400 text-red-600")}
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Окончание</label>
                <input
                  type="time" min="08:00" max="22:00"
                  className={cn("input", (durationMin <= 0 || endMin > CLOSE_MIN) && "border-red-400 text-red-600")}
                  value={endTime} onChange={(e) => setEndTime(e.target.value)}
                />
              </div>
            </div>
            <div className="text-sm text-stone-500 mt-2">
              {durationMin <= 0 ? (
                <span className="text-red-600">Окончание должно быть позже начала.</span>
              ) : outsideHours ? (
                <span className="text-red-600">Клуб работает с 08:00 до 22:00 — выберите время внутри этого окна.</span>
              ) : (
                <>Длительность: <span className="font-mono">{durationMin} мин</span></>
              )}
            </div>
          </Section>

          {/* 2. Категория */}
          <Section title="2. Категория бронирования" icon={MapPin}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {(catalog?.categories || []).map((c) => (
                <button
                  key={c.code}
                  type="button"
                  onClick={() => setCategory(c.code)}
                  className={cn(
                    "text-left rounded-xl border-2 p-4 transition",
                    category === c.code
                      ? "border-brand bg-brand/5 ring-1 ring-brand/20"
                      : "border-stone-200 hover:border-brand/40 bg-white"
                  )}
                >
                  <div className="text-sm font-semibold text-stone-900">{c.short}</div>
                  <div className="text-xs text-stone-500 mt-0.5">{c.detail}</div>
                  <div className="mt-3 text-xl font-bold text-brand">
                    {formatRub(c.base_price_kopecks)}
                    {c.basket_unit && <span className="text-xs text-stone-400 font-normal"> /корзина</span>}
                    {c.per_guest && <span className="text-xs text-stone-400 font-normal"> /гость</span>}
                  </div>
                  <div className="text-[11px] text-stone-400 mt-1">
                    вместимость: {c.pool_capacity} {c.pool_capacity === 1 ? "слот" : "мест"}
                  </div>
                </button>
              ))}
            </div>
          </Section>

          {/* 3. Гости */}
          <Section title="3. Количество гостей" icon={UsersIcon}>
            <div className="flex items-center gap-2 flex-wrap">
              {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => {
                const disabled = hasTraining && n > 4;
                return (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setGuests(n)}
                    disabled={disabled}
                    className={cn(
                      "w-10 h-10 rounded-lg border font-semibold transition",
                      guests === n
                        ? "bg-brand text-white border-brand"
                        : "bg-white border-stone-300 text-stone-700 hover:bg-stone-50",
                      disabled && "opacity-40 cursor-not-allowed"
                    )}
                  >
                    {n}
                  </button>
                );
              })}
              <div className="flex items-center gap-2 ml-1">
                <span className="text-sm text-stone-500">или</span>
                <input
                  type="number"
                  min={1}
                  max={hasTraining ? 4 : 99}
                  value={guests}
                  onChange={(e) => {
                    const n = Math.max(1, Math.min(hasTraining ? 4 : 99, Number(e.target.value) || 1));
                    setGuests(n);
                  }}
                  className={cn(
                    "w-20 h-10 rounded-lg border px-2 text-center font-semibold",
                    guests > 8
                      ? "bg-brand text-white border-brand"
                      : "bg-white border-stone-300 text-stone-700"
                  )}
                  title="Введите любое число"
                  data-testid="guests-custom-input"
                />
              </div>
              {hasTraining && (
                <div className="text-xs text-stone-500 ml-2">С тренировкой поддерживаются 1–4 гостей.</div>
              )}
            </div>
            {perGuest && activeCategory && (
              <div className="mt-3 text-sm text-stone-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                Выходной тариф: мячи без лимита, цена × количество гостей.
                <div className="mt-1 font-semibold text-stone-800">
                  {guests} × {formatRub(activeCategory.base_price_kopecks)} ={" "}
                  <span className="text-brand">{formatRub(activeCategory.base_price_kopecks * guests)}</span>
                </div>
              </div>
            )}
          </Section>

          {/* 3b. Корзины — только для range_weekday_basket */}
          {usesBaskets && (
            <Section title="3a. Количество корзин" icon={UsersIcon}>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="inline-flex items-center bg-white border border-stone-300 rounded-lg overflow-hidden">
                  <button
                    type="button"
                    className="w-10 h-10 text-lg font-semibold hover:bg-stone-50 disabled:opacity-40"
                    onClick={() => setBaskets((b) => Math.max(1, b - 1))}
                    disabled={baskets <= 1}
                  >−</button>
                  <div className="w-14 text-center font-semibold text-lg">{baskets}</div>
                  <button
                    type="button"
                    className="w-10 h-10 text-lg font-semibold hover:bg-stone-50 disabled:opacity-40"
                    onClick={() => setBaskets((b) => Math.min(20, b + 1))}
                    disabled={baskets >= 20}
                  >+</button>
                </div>
                <div className="text-sm text-stone-600">
                  {baskets} × {formatRub(activeCategory?.base_price_kopecks ?? 0)} ={" "}
                  <span className="font-semibold">
                    {formatRub((activeCategory?.base_price_kopecks ?? 0) * baskets)}
                  </span>
                </div>
                {baskets < guests && (
                  <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    На {guests} гостей обычно нужно больше корзин.
                  </div>
                )}
              </div>
              <div className="text-xs text-stone-500 mt-2">
                1 корзина = 40 мячей. При 6 гостях администратор может сразу записать 2–3 корзины.
              </div>
            </Section>
          )}

          {/* 4. Клиент */}
          <Section title="4. Клиент">
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2 mb-2">
              <input
                type="text"
                className="input"
                placeholder="Поиск клиента по имени или телефону"
                value={customerQuery}
                onChange={(e) => { setCustomerQuery(e.target.value); setCustomerId(null); }}
              />
              <button
                type="button"
                className="btn-ghost border border-stone-300 rounded-lg px-3 py-2 text-sm"
                onClick={() => setShowQuickCreate((v) => !v)}
              >
                {showQuickCreate ? "Отмена" : "+ Быстро создать"}
              </button>
            </div>

            {showQuickCreate ? (
              <div className="space-y-2">
                <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
                  <input
                    className="input"
                    placeholder="ФИО гостя"
                    value={quickName}
                    onChange={(e) => setQuickName(e.target.value)}
                  />
                  <input
                    className="input"
                    inputMode="tel"
                    placeholder="+7 (___) ___-__-__ (необязательно)"
                    value={quickPhone}
                    onChange={(e) => {
                      const digits = extractRuDigits(e.target.value);
                      setQuickPhone(digits ? formatRuPhone(digits) : "");
                    }}
                  />
                  <button
                    type="button"
                    disabled={!quickName.trim() || createCustomer.isPending}
                    onClick={() => createCustomer.mutate()}
                    className="btn-primary whitespace-nowrap"
                  >
                    Создать
                  </button>
                </div>
                <div className="text-xs text-stone-500">
                  Телефон можно не указывать. Формат российский: +7 (999) 123-45-67.
                </div>
              </div>
            ) : (
              <div className="max-h-48 overflow-auto border border-stone-200 rounded-lg divide-y divide-stone-100">
                {filteredCustomers.length === 0 && (
                  <div className="p-3 text-sm text-stone-400 text-center">Нет клиентов</div>
                )}
                {filteredCustomers.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => { setCustomerId(c.id); setCustomerQuery(c.name); }}
                    className={cn(
                      "w-full text-left px-3 py-2 text-sm hover:bg-brand/5 transition",
                      customerId === c.id && "bg-brand/10 text-brand"
                    )}
                  >
                    <div className="font-medium">{c.name}</div>
                    {c.phone && <div className="text-xs text-stone-500">{c.phone}</div>}
                  </button>
                ))}
              </div>
            )}
          </Section>

          {/* 5. Тренировка */}
          <Section title="5. Нужна ли тренировка?" icon={GraduationCap}>
            {isInstructor ? (
              <div className="mb-3 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2 text-sm text-emerald-800">
                Вы создаёте бронь с тренировкой у себя — выберите тип ниже.
              </div>
            ) : (
              <div className="flex gap-2 mb-3">
                <YesNoChip active={!hasTraining} onClick={() => setHasTraining(false)}>Нет</YesNoChip>
                <YesNoChip active={hasTraining} onClick={() => setHasTraining(true)}>Да</YesNoChip>
              </div>
            )}

            {hasTraining && (
              <div className="space-y-4">
                <div>
                  <div className="label">Тип тренировки</div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {(catalog?.trainings || []).map((t) => {
                      const price = t.prices.find((p) => p.guests === guests)?.price_kopecks ?? null;
                      return (
                        <button
                          key={t.type}
                          type="button"
                          onClick={() => setTrainingType(t.type)}
                          className={cn(
                            "text-left rounded-lg border-2 p-3 transition",
                            trainingType === t.type
                              ? "border-brand bg-brand/5"
                              : "border-stone-200 hover:border-brand/40 bg-white"
                          )}
                        >
                          <div className="font-semibold text-sm">{t.label}</div>
                          <div className="text-lg font-bold text-brand mt-1">
                            {price != null ? formatRub(price) : "—"}
                          </div>
                          <div className="text-[11px] text-stone-400">для {guests} {guests === 1 ? "гостя" : "гостей"}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="label">Тренер</label>
                  {isInstructor ? (
                    <div
                      className="input bg-stone-50 text-stone-700 cursor-not-allowed select-none"
                      data-testid="trainer-locked-self"
                      title="Тренер может создавать брони только на себя"
                    >
                      Вы — {me?.name || "тренер"}
                    </div>
                  ) : (
                    <select
                      className="input"
                      value={trainerId ?? ""}
                      onChange={(e) => setTrainerId(e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">— выберите тренера —</option>
                      {(instructors || []).map((i) => (
                        <option key={i.id} value={i.id}>{i.name} · {i.specialization}</option>
                      ))}
                    </select>
                  )}
                </div>
              </div>
            )}
          </Section>

          {/* 6. Промокод и абонемент */}
          <Section title="6. Промокод или абонемент" icon={Ticket}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Промокод</label>
                <input
                  className={cn(
                    "input font-mono uppercase tracking-wider",
                    quote?.coupon_error && couponCode && "border-red-400 text-red-600"
                  )}
                  placeholder="Например: SUMMER10"
                  value={couponCode}
                  onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                />
                {couponCode && quote?.coupon_label && !quote.coupon_error && (
                  <div className="text-xs text-emerald-700 mt-1">Применён: {quote.coupon_label}</div>
                )}
                {couponCode && quote?.coupon_error && (
                  <div className="text-xs text-red-600 mt-1">{quote.coupon_error}</div>
                )}
              </div>
              <div>
                <label className="label">Абонемент клиента</label>
                <select
                  className="input"
                  value={membershipId ?? ""}
                  onChange={(e) => setMembershipId(e.target.value ? Number(e.target.value) : null)}
                  disabled={!customerId || activeMemberships.length === 0}
                >
                  <option value="">
                    {!customerId
                      ? "— сначала выберите клиента —"
                      : activeMemberships.length === 0
                        ? "— у клиента нет активных абонементов —"
                        : "— без абонемента —"}
                  </option>
                  {activeMemberships.map((m) => {
                    const parts: string[] = [];
                    if (m.plan_covers_training) {
                      if (m.plan_max_trainings > 0) {
                        const left = Math.max(0, m.plan_max_trainings - m.trainings_used);
                        parts.push(`тренировки ${left}/${m.plan_max_trainings}`);
                      } else {
                        parts.push("тренировки ∞");
                      }
                    }
                    if (m.plan_discount_percent > 0) parts.push(`−${m.plan_discount_percent}%`);
                    parts.push(`до ${m.ends_on}`);
                    return (
                      <option key={m.id} value={m.id}>
                        {m.plan_name} · {parts.join(" · ")}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          </Section>

          {/* 7. Комментарий */}
          <Section title="7. Комментарий">
            <textarea
              className="input min-h-[72px] font-sans"
              placeholder="Например: день рождения, VIP-гость, нужен напиток"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </Section>
        </div>

        {/* RIGHT: summary */}
        <aside className="bg-stone-50 border-l border-stone-200 p-6 lg:sticky lg:top-0 lg:self-start lg:max-h-[90vh] overflow-auto">
          <div className="flex items-center gap-2 mb-3">
            <Calculator size={18} className="text-brand" />
            <h3 className="text-lg font-semibold">Итог брони</h3>
          </div>

          <SummaryRow label="Категория" value={quote?.category_short ?? "—"} sub={quote?.category_detail} />
          <SummaryRow
            label="Дата и время"
            value={`${startDate} · ${startTime}–${endTime}`}
          />
          <SummaryRow label="Гостей" value={String(guests)} />
          {quote?.basket_unit && (
            <SummaryRow
              label="Корзин"
              value={`${quote.baskets} × ${formatRub(quote.basket_unit_price_kopecks)}`}
            />
          )}
          <SummaryRow
            label="Тренировка"
            value={hasTraining ? (quote?.training_label || "—") : "нет"}
          />
          {hasTraining && (
            <SummaryRow label="Тренер" value={quote?.trainer_name || "—"} />
          )}

          <div className="my-4 border-t border-stone-200" />

          <PriceRow
            label={
              quote?.basket_unit
                ? `Базовая цена (${quote.baskets} корзин${quote.baskets === 1 ? "а" : ""})`
                : perGuest
                  ? `Базовая цена (${guests} × ${formatRub(activeCategory?.base_price_kopecks ?? 0)})`
                  : "Базовая цена"
            }
            k={quote?.base_price_kopecks ?? 0}
          />
          <PriceRow label="Тренировка" k={quote?.training_price_kopecks ?? 0} />
          {(quote?.membership_discount_kopecks ?? 0) > 0 && (
            <PriceRow
              label={quote?.membership_label ? `Абонемент · ${quote.membership_label}` : "Скидка по абонементу"}
              k={-(quote?.membership_discount_kopecks ?? 0)}
            />
          )}
          {(quote?.coupon_discount_kopecks ?? 0) > 0 && (
            <PriceRow
              label={quote?.coupon_label ? `Промокод · ${quote.coupon_label}` : "Скидка по промокоду"}
              k={-(quote?.coupon_discount_kopecks ?? 0)}
            />
          )}

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-base font-semibold">Итого</span>
            <span className="text-2xl font-bold text-brand">
              {formatRub(quote?.total_kopecks ?? 0)}
            </span>
          </div>

          <div className="my-4 border-t border-stone-200" />

          <StatusRow availability={quote?.resource_availability} />
          {hasTraining && <StatusRow availability={quote?.trainer_availability} />}

          {quote?.errors && quote.errors.length > 0 && (
            <div className="mt-3 rounded-lg bg-red-50 border border-red-200 p-3">
              <div className="flex items-center gap-2 text-red-700 font-medium text-sm mb-1">
                <AlertCircle size={16} /> Ошибки:
              </div>
              <ul className="list-disc pl-5 text-sm text-red-700 space-y-0.5">
                {quote.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}
          {quote?.warnings && quote.warnings.length > 0 && (
            <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
              {quote.warnings.join(" · ")}
            </div>
          )}
          {customerId == null && (
            <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
              Выберите клиента или создайте нового.
            </div>
          )}
          {save.error && (
            <div className="mt-3 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {(save.error as Error).message}
            </div>
          )}

          <button
            onClick={() => save.mutate()}
            disabled={!canSave}
            className={cn(
              "mt-5 w-full flex items-center justify-center gap-2 rounded-lg px-4 py-3 font-semibold transition",
              canSave ? "bg-brand text-white hover:bg-brand-dark" : "bg-stone-200 text-stone-500 cursor-not-allowed"
            )}
          >
            {save.isPending ? <Loader2 size={18} className="animate-spin" /> : <CheckCircle2 size={18} />}
            Сохранить бронь
          </button>
          <button
            onClick={onClose}
            className="mt-2 w-full rounded-lg px-4 py-2 text-stone-600 hover:bg-stone-100 transition"
          >
            Отмена
          </button>
        </aside>
      </div>
    </div>
  );
}

function Section({
  title, icon: Icon, children,
}: { title: string; icon?: any; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <div className="flex items-center gap-2 mb-2 text-stone-800">
        {Icon && <Icon size={16} className="text-brand" />}
        <h3 className="font-semibold">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function YesNoChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-5 py-2 rounded-lg border-2 font-semibold transition",
        active ? "border-brand bg-brand text-white" : "border-stone-300 text-stone-700 hover:border-brand/40"
      )}
    >
      {children}
    </button>
  );
}

function SummaryRow({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="mb-2">
      <div className="text-xs uppercase tracking-wide text-stone-500">{label}</div>
      <div className="text-sm font-medium text-stone-900">{value}</div>
      {sub && <div className="text-xs text-stone-500">{sub}</div>}
    </div>
  );
}

function PriceRow({ label, k }: { label: string; k: number }) {
  const negative = k < 0;
  return (
    <div className="flex items-center justify-between text-sm">
      <span className={cn("text-stone-600", negative && "text-emerald-700")}>{label}</span>
      <span className={cn("font-medium", negative && "text-emerald-700")}>{formatRub(k)}</span>
    </div>
  );
}

function StatusRow({ availability }: { availability?: { ok: boolean; message: string } }) {
  if (!availability || !availability.message) return null;
  const ok = availability.ok;
  return (
    <div className={cn(
      "flex items-start gap-2 text-sm rounded-lg p-2",
      ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"
    )}>
      {ok ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <AlertCircle size={16} className="mt-0.5 shrink-0" />}
      <span>{availability.message}</span>
    </div>
  );
}
