"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowDown, ArrowUpRight, CalendarDays, CheckCircle2, GitPullRequest, Radio, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { GoogleLoginButton, googleSignInEnabled } from "@/components/google-login-button";
import { EmailPasswordAuthForm } from "@/components/email-password-auth-form";
import { TryDemoButton } from "@/components/try-demo-button";
import { Separator } from "@/components/ui/separator";
import { Waveform, Wordmark } from "@/components/brand";


export default function LoginPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  return <div className="engagement-login">
    <section className="login-ink"><Link href="/" className="landing-wordmark">Wilco</Link><div><h1>Heard.<span>Will comply.</span></h1><p>Meetings in Hinglish, notes with owners.</p></div><span>Gnani Prisma v3 · Gnani Timbre</span></section>
    <section className="login-working-sheet"><div><h2 className="two-tone">Welcome back.<span>Let’s get to work.</span></h2><TryDemoButton/><div className="flex items-center gap-3"><Separator className="flex-1"/><span className="text-xs text-muted-foreground">or sign in</span><Separator className="flex-1"/></div>{googleSignInEnabled&&<GoogleLoginButton/>}<EmailPasswordAuthForm/><Link href="/extension" className="text-sm underline">Chrome extension</Link></div></section>
  </div>;
}
