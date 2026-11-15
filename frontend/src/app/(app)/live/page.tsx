import type { Metadata } from "next";
import { LiveSession } from "@/components/live-session";
import "../../hackathon-intelligence.css";

export const metadata: Metadata = { title: "Wilco Live" };

export default function LivePage() {
  return <div className="signal-intelligence-page signal-live-page"><LiveSession /></div>;
}
