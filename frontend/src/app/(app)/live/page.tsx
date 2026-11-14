import type { Metadata } from "next";
import { LiveSession } from "@/components/live-session";

export const metadata: Metadata = { title: "Charcha Live" };

export default function LivePage() {
  return <LiveSession />;
}
