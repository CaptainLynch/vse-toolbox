// Unsaved-changes guard for the plan page (legacy setupOverviewGuards +
// overviewConfirmDiscard): a beforeunload prompt plus an in-page confirm when
// a click would navigate away (any "#..." link, legacy panel links, plugin nav).
import { useEffect, useRef } from "/static/host/vendor/preact-htm.js";
import { DISCARD_CONFIRM } from "./logic.js";

function leavingTarget(event, root) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const target = event.target && event.target.closest ? event.target.closest("a[href], [data-panel-link]") : null;
  if (!target) return null;
  if (target.matches("[data-panel-link]")) return target;
  const href = target.getAttribute("href") || "";
  if (!href.startsWith("#")) return null;
  if (href === window.location.hash) return null;
  // Links inside the page that keep us on the plan page (none today) stay free.
  if (root && root.contains(target) && href.startsWith("#p/project-overview/plan")) return null;
  return target;
}

/**
 * isDirty(): boolean, read at event time. onDiscard(): drop the draft once the
 * user agreed to leave.
 */
export function useLeaveGuard(isDirty, onDiscard, rootRef) {
  const latest = useRef({ isDirty, onDiscard });
  latest.current = { isDirty, onDiscard };

  useEffect(() => {
    const onBeforeUnload = (event) => {
      if (!latest.current.isDirty()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event) => {
      if (!latest.current.isDirty()) return;
      if (!leavingTarget(event, rootRef && rootRef.current)) return;
      if (window.confirm(DISCARD_CONFIRM)) {
        latest.current.onDiscard();
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, []);
}
