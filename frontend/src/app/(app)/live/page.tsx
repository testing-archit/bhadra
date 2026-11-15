import type { Metadata } from "next";
import { LiveSession } from "@/components/live-session";


export const metadata: Metadata = { title: "Wilco Live" };

export default function LivePage() {
  return <div className="engagement-live"><LiveSession /></div>;
}
