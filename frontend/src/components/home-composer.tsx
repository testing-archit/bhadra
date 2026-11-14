"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowUp, Link2, Mic, Upload } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { VoiceAskButton } from "@/components/voice-ask-button";
import { useShell } from "@/components/shell/shell-context";

export function HomeComposer() {
  const router = useRouter();
  const { openNotetaker } = useShell();
  const [mode, setMode] = useState("capture");
  const [link, setLink] = useState("");
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  function ask(text: string, voice = false) {
    if (text.trim())
      router.push(
        `/memory?q=${encodeURIComponent(text.trim())}${voice ? "&voice=1" : ""}`,
      );
  }
  return (
    <div className="home-composer">
      <Tabs
        value={mode}
        onValueChange={(value) => {
          setMode(String(value));
          setError("");
        }}
      >
        <TabsList
          variant="line"
          className="mx-5 mt-3 sm:mx-6"
          aria-label="Start with Wilco"
        >
          <TabsTrigger value="capture">Join a meeting</TabsTrigger>
          <TabsTrigger value="ask">Ask your meetings</TabsTrigger>
        </TabsList>
        <TabsContent value="capture" className="px-5 pt-3 sm:px-6">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              openNotetaker(link.trim());
            }}
          >
            <label className="sr-only" htmlFor="home-meeting-link">
              Meeting link
            </label>
            <div className="flex items-center gap-3">
              <Link2
                className="size-5 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <input
                id="home-meeting-link"
                value={link}
                onChange={(event) => setLink(event.target.value)}
                placeholder="Paste a Meet or Teams link"
                inputMode="url"
                autoComplete="off"
                className="h-14 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground sm:text-lg"
              />
              <button
                type="submit"
                className="composer-send"
                aria-label="Continue with meeting link"
              >
                <ArrowUp className="size-5" />
              </button>
            </div>
          </form>
        </TabsContent>
        <TabsContent value="ask" className="px-5 pt-3 sm:px-6">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              ask(question);
            }}
          >
            <label className="sr-only" htmlFor="home-question">
              Question about your meetings
            </label>
            <div className="flex items-center gap-3">
              <input
                id="home-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="What did we decide about the launch?"
                className="h-14 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground sm:text-lg"
              />
              <VoiceAskButton
                onQuestion={(text) => ask(text, true)}
                onError={setError}
              />
              <button
                type="submit"
                disabled={!question.trim()}
                className="composer-send"
                aria-label="Ask Wilco"
              >
                <ArrowUp className="size-5" />
              </button>
            </div>
          </form>
        </TabsContent>
      </Tabs>
      {error && (
        <p className="px-6 pt-2 text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      <div className="composer-footer">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span
            className="size-1.5 rounded-full bg-success"
            aria-hidden="true"
          />
          {mode === "capture"
            ? "Visible participant. Recording with consent."
            : "Answers grounded in your meetings."}
        </span>
        <div className="flex items-center gap-3">
          <Link href="/record" className="composer-alternative">
            <Mic className="size-3.5" aria-hidden="true" /> Record
          </Link>
          <Link
            href="/meetings/new?source=upload"
            className="composer-alternative"
          >
            <Upload className="size-3.5" aria-hidden="true" /> Upload
          </Link>
        </div>
      </div>
    </div>
  );
}
