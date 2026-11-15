"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Landing } from "@/components/landing";

export default function RootPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if(user) router.replace("/dashboard");
  }, [loading, user, router]);

  return loading||user?null:<Landing/>;
}
