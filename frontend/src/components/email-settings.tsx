"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChevronRight, KeyRound, Loader2, Mail } from "lucide-react";
import { api, ApiError, type EmailPreferences, type EmailPreferencesUpdate, type EmailSchedule } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const selectClass = "h-8 rounded-lg border bg-background px-2.5 text-sm text-foreground";

function hourLabel(hour: number) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function Switch({ on, busy, disabled, label, small, onChange }: {
  on: boolean;
  busy?: boolean;
  disabled?: boolean;
  label: string;
  small?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={busy || disabled}
      onClick={() => onChange(!on)}
      className={cn(
        "relative mt-0.5 shrink-0 rounded-full transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50",
        small ? "h-4 w-7" : "h-5 w-9",
        on ? "bg-primary" : "bg-input",
      )}
    >
      {busy ? (
        <Loader2 className="absolute inset-0 m-auto size-3 animate-spin text-primary-foreground" />
      ) : (
        <span
          className={cn(
            "absolute top-0.5 left-0.5 rounded-full bg-background shadow-sm transition-transform",
            small ? "size-3" : "size-4",
            on && (small ? "translate-x-3" : "translate-x-4"),
          )}
        />
      )}
    </button>
  );
}

/** Which emails Charcha sends this person, and when the scheduled ones
 * arrive. A group's switch turns all its emails off; inside a group each
 * email has its own. Security email can't be turned off; everything else
 * can, here or from any email's unsubscribe link (which turns off the group). */
export function EmailSettings() {
  const [prefs, setPrefs] = useState<EmailPreferences | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getEmailPreferences().then(setPrefs).catch(() => setError("Email preferences couldn't be loaded."));
  }, []);

  async function save(busy: string, update: EmailPreferencesUpdate, optimistic: EmailPreferences) {
    if (!prefs) return;
    setBusyKey(busy);
    setError(null);
    const previous = prefs;
    setPrefs(optimistic);
    try {
      setPrefs(await api.updateEmailPreferences(update));
    } catch (cause) {
      setPrefs(previous);
      setError(cause instanceof ApiError ? cause.message : "That change wasn't saved.");
    } finally {
      setBusyKey(null);
    }
  }

  function toggleGroup(key: string, enabled: boolean) {
    if (!prefs) return;
    void save(key, { categories: { [key]: enabled } }, {
      ...prefs,
      categories: prefs.categories.map((c) => (c.key === key ? { ...c, enabled } : c)),
    });
  }

  function toggleEmail(key: string, enabled: boolean) {
    if (!prefs) return;
    void save(key, { kinds: { [key]: enabled } }, {
      ...prefs,
      categories: prefs.categories.map((c) => ({ ...c, emails: c.emails.map((e) => (e.key === key ? { ...e, enabled } : e)) })),
    });
  }

  function setSchedule(busy: string, change: Partial<EmailSchedule>) {
    if (!prefs) return;
    void save(busy, { schedule: change }, { ...prefs, schedule: { ...prefs.schedule, ...change } });
  }

  function toggleDay(day: number) {
    if (!prefs) return;
    const days = prefs.schedule.reminder_days;
    setSchedule("reminder_days", { reminder_days: days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort() });
  }

  function expand(key: string) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <Card id="email">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><Mail className="h-4 w-4 text-primary" /> Email</CardTitle>
        <CardDescription>
          {prefs ? <>Sent to <span className="font-medium text-foreground">{prefs.address}</span> from charcha@example.com. Choose which emails you get and when. In-app notifications don&apos;t change.</> : "Loading…"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        {prefs && !prefs.enabled && (
          <p className="mb-2 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground">Email isn&apos;t switched on for this workspace yet; your choices apply once it is.</p>
        )}
        {prefs?.categories.map((category) => {
          const expanded = open.has(category.key);
          const onCount = category.emails.filter((e) => e.enabled).length;
          const groupOn = category.enabled || !category.can_disable;
          return (
            <div key={category.key} className="rounded-lg px-1 py-2.5">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{category.label}</p>
                  <p className="text-xs text-muted-foreground">{category.description}</p>
                  {category.emails.length > 0 && (
                    <button
                      type="button"
                      onClick={() => expand(category.key)}
                      aria-expanded={expanded}
                      className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                    >
                      <ChevronRight className={cn("size-3 transition-transform", expanded && "rotate-90")} />
                      {!category.can_disable
                        ? `${category.emails.length} email${category.emails.length === 1 ? "" : "s"}`
                        : !category.enabled
                          ? "All off"
                          : `${onCount} of ${category.emails.length} on`}
                      {category.key === "reminders" && groupOn && " · choose days"}
                      {category.key === "digest" && groupOn && ` · ${WEEKDAYS[prefs.schedule.digest_day]}s`}
                    </button>
                  )}
                </div>
                {category.can_disable ? (
                  <Switch on={category.enabled} busy={busyKey === category.key} label={`${category.label} emails`} onChange={(on) => toggleGroup(category.key, on)} />
                ) : (
                  <span className="mt-0.5 shrink-0 text-xs text-muted-foreground">Always on</span>
                )}
              </div>
              {expanded && (
                <div className="mt-2 ml-4 flex flex-col gap-2 border-l pl-3">
                  {category.emails.map((email) => (
                    <div key={email.key} className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <p className={cn("text-sm", !groupOn && "text-muted-foreground")}>{email.label}</p>
                        <p className="text-xs text-muted-foreground">{email.description}</p>
                      </div>
                      {category.can_disable ? (
                        <Switch
                          small
                          on={groupOn && email.enabled}
                          disabled={!groupOn}
                          busy={busyKey === email.key}
                          label={email.label}
                          onChange={(on) => toggleEmail(email.key, on)}
                        />
                      ) : (
                        <span className="mt-0.5 shrink-0 text-xs text-muted-foreground">Always on</span>
                      )}
                    </div>
                  ))}
                  {category.key === "reminders" && groupOn && (
                    <div>
                      <p className="text-xs text-muted-foreground">Send on</p>
                      <div className="mt-1 flex flex-wrap gap-1" role="group" aria-label="Reminder days">
                        {WEEKDAYS.map((day, index) => {
                          const on = prefs.schedule.reminder_days.includes(index);
                          return (
                            <button
                              key={day}
                              type="button"
                              aria-pressed={on}
                              disabled={busyKey === "reminder_days"}
                              onClick={() => toggleDay(index)}
                              className={cn(
                                "h-7 rounded-md border px-2 text-xs font-medium transition-colors disabled:opacity-50",
                                on ? "border-primary bg-primary text-primary-foreground" : "bg-background text-muted-foreground hover:text-foreground",
                              )}
                            >
                              {day.slice(0, 3)}
                            </button>
                          );
                        })}
                      </div>
                      {prefs.schedule.reminder_days.length === 0 && (
                        <p className="mt-1 text-xs text-muted-foreground">No days picked, so no reminders will be sent.</p>
                      )}
                    </div>
                  )}
                  {category.key === "digest" && groupOn && (
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                      Send on
                      <select
                        value={prefs.schedule.digest_day}
                        disabled={busyKey === "digest_day"}
                        onChange={(event) => setSchedule("digest_day", { digest_day: Number(event.target.value) })}
                        className={selectClass}
                      >
                        {WEEKDAYS.map((day, index) => <option key={day} value={index}>{day}</option>)}
                      </select>
                    </label>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {prefs && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border-t px-1 pt-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">Morning emails arrive at</p>
              <p className="text-xs text-muted-foreground">The due-task reminder and weekly digest, India time.</p>
            </div>
            <select
              value={prefs.schedule.hour}
              disabled={busyKey === "hour"}
              aria-label="Morning email time"
              onChange={(event) => setSchedule("hour", { hour: Number(event.target.value) })}
              className={selectClass}
            >
              {prefs.send_hours.map((hour) => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}
            </select>
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

/** Set or change the Charcha password. Changing it signs out every other
 * session and emails a confirmation. */
export function PasswordSettings() {
  const { user, login } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const hasPassword = user?.has_password ?? true;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await login(await api.changePassword(hasPassword ? current : null, next));
      setCurrent("");
      setNext("");
      setMessage({ tone: "ok", text: "Password saved. You've been signed out everywhere else." });
    } catch (cause) {
      setMessage({ tone: "error", text: cause instanceof ApiError ? cause.message : "The password wasn't saved." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="password">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><KeyRound className="h-4 w-4 text-primary" /> Password</CardTitle>
        <CardDescription>
          {hasPassword ? "Change the password you use to sign in with your email." : "You sign in with Google. Add a password to also sign in with your email."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-3 sm:max-w-sm">
          {hasPassword && (
            <div className="grid gap-1.5">
              <Label htmlFor="current-password">Current password</Label>
              <Input id="current-password" type="password" required autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} />
            </div>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="settings-new-password">New password</Label>
            <Input id="settings-new-password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} />
          </div>
          {message && <p className={cn("text-sm", message.tone === "error" ? "text-destructive" : "text-success")}>{message.text}</p>}
          <Button type="submit" disabled={busy} className="w-fit">{busy ? "Saving…" : hasPassword ? "Change password" : "Add password"}</Button>
        </form>
      </CardContent>
    </Card>
  );
}
