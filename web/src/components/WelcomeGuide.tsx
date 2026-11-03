import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useFields, useRuns } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";

/** The pages a new user lands on: the guide shows on top of them until it is dismissed. */
export const WELCOME_PAGES = ["/topics", "/screening", "/search", "/results"];

const storageKey = (userId: string) => `welcome-dismissed:${userId}`;

function readDismissed(userId: string | undefined): boolean {
  if (!userId) return false;
  try {
    return window.localStorage.getItem(storageKey(userId)) === "1";
  } catch {
    return false;
  }
}

function writeDismissed(userId: string | undefined, dismissed: boolean) {
  if (!userId) return;
  try {
    if (dismissed) window.localStorage.setItem(storageKey(userId), "1");
    else window.localStorage.removeItem(storageKey(userId));
  } catch {
    // storage blocked (private window): the choice lasts until the page reloads
  }
}

type Welcome = { open: boolean; dismiss: () => void; reopen: () => void };
const WelcomeContext = createContext<Welcome>({ open: false, dismiss: () => undefined, reopen: () => undefined });

/** Whether the first-use guide is open, per user (remembered in this browser). */
export function WelcomeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const userId = user?.id;
  // the choice made in this page view; null = follow what the browser remembers for this user
  const [choice, setChoice] = useState<{ user: string | undefined; dismissed: boolean } | null>(null);
  const dismissed = choice && choice.user === userId ? choice.dismissed : readDismissed(userId);
  const dismiss = useCallback(() => {
    writeDismissed(userId, true);
    setChoice({ user: userId, dismissed: true });
  }, [userId]);
  const reopen = useCallback(() => {
    writeDismissed(userId, false);
    setChoice({ user: userId, dismissed: false });
  }, [userId]);
  const value = useMemo(() => ({ open: !!userId && !dismissed, dismiss, reopen }), [userId, dismissed, dismiss, reopen]);
  return <WelcomeContext.Provider value={value}>{children}</WelcomeContext.Provider>;
}

export const useWelcome = () => useContext(WelcomeContext);

/** The 3-step welcome card: create a topic → start a search → read the results, each marked done from the data. */
export function WelcomeGuide() {
  const { user } = useAuth();
  const { dismiss } = useWelcome();
  const fields = useFields();
  const runs = useRuns();
  const member = hasRole(user, "member");
  const hasTopic = (fields.data ?? []).length > 0;
  const allRuns = runs.data ?? [];
  const hasSearch = allRuns.length > 0;
  const finished = allRuns.find((run) => run.status === "done" && run.paper_count > 0);
  const steps = [
    {
      title: "Create a topic",
      text: "Describe in plain words the research question you want papers for. We suggest keywords and criteria; you keep what fits.",
      to: member ? "/topics/new" : "/topics",
      link: member ? "Create a topic" : "See the topics",
      done: hasTopic,
    },
    {
      title: "Start a search",
      text: "Pick the topic and start a search. It looks for papers in the sources, keeps the relevant ones and reviews them. Demo mode costs nothing.",
      to: "/screening",
      link: member ? "Start a search" : "See the searches",
      done: hasSearch,
    },
    {
      title: "Read the results",
      text: "Open the results of a finished search: the best papers come first, each with the reason in one sentence. Save the good ones to a library.",
      to: finished ? `/results?run=${finished.id}` : "/results",
      link: "Read the results",
      done: !!finished,
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  return (
    <section className="welcome" aria-labelledby="welcome-title">
      <div className="welcome__head">
        <div>
          <p className="kicker">How it works</p>
          <h2 id="welcome-title">From a question to papers worth reading, in 3 steps</h2>
          <p className="sub">{doneCount === 3 ? "You have done all three steps. Hide this guide; the How it works link at the top brings it back." : `${doneCount} of 3 done. Each step links to the place where you do it.`}</p>
        </div>
        <button type="button" className="welcome__close" onClick={dismiss}>Hide this guide</button>
      </div>
      <ol className="welcome__steps">
        {steps.map((step, i) => (
          <li key={step.title} className={step.done ? "is-done" : undefined}>
            <span className="welcome__num" aria-hidden="true">{step.done ? "✓" : i + 1}</span>
            <h3>{step.title}{step.done && <span className="welcome__state"> · done</span>}</h3>
            <p>{step.text}</p>
            <Link to={step.to}>{step.link}<span className="sr-only">{step.done ? " (done)" : ""}</span></Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
