"use client";

import { useCallback, useEffect, useRef } from "react";

const CHANNEL_NAME = "links-reader-sync";

interface DetachableReaderProps {
  /** Whether the reader is currently detached */
  detached: boolean;
  /** Called when user requests undock */
  onDetach: () => void;
  /** Called when detached window closes */
  onReattach: () => void;
  /** Current link ID to display in detached reader */
  currentLinkId: string | null;
  /** Content to render when attached */
  children: React.ReactNode;
}

/**
 * DetachableReader: "Undock" button pops reader into separate window.
 * j/k in main window syncs the detached reader via BroadcastChannel.
 */
export function DetachableReader({
  detached,
  onDetach,
  onReattach,
  currentLinkId,
  children,
}: DetachableReaderProps) {
  const windowRef = useRef<Window | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);

  // Set up BroadcastChannel
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    channelRef.current = new BroadcastChannel(CHANNEL_NAME);
    return () => {
      channelRef.current?.close();
    };
  }, []);

  // Send link ID updates to detached window
  useEffect(() => {
    if (detached && currentLinkId && channelRef.current) {
      channelRef.current.postMessage({
        type: "navigate",
        linkId: currentLinkId,
      });
    }
  }, [detached, currentLinkId]);

  // Monitor detached window close
  useEffect(() => {
    if (!detached || !windowRef.current) return;
    const interval = setInterval(() => {
      if (windowRef.current?.closed) {
        windowRef.current = null;
        onReattach();
      }
    }, 500);
    return () => clearInterval(interval);
  }, [detached, onReattach]);

  // Clean up on unmount (page navigation away from /links)
  useEffect(() => {
    return () => {
      if (windowRef.current && !windowRef.current.closed) {
        windowRef.current.close();
        windowRef.current = null;
      }
    };
  }, []);

  const handleDetach = useCallback(() => {
    const w = window.open(
      `/links/reader-detached${currentLinkId ? `?link_id=${currentLinkId}` : ""}`,
      "links-reader",
      "width=700,height=900,menubar=no,toolbar=no,status=no"
    );
    if (w) {
      windowRef.current = w;
      onDetach();
    }
  }, [currentLinkId, onDetach]);

  if (detached) {
    return (
      <div className="flex items-center justify-center h-full bg-surface-1 rounded-lg border border-border">
        <div className="text-center">
          <p className="text-sm text-text-muted mb-2">Reader detached to separate window</p>
          <button
            onClick={() => {
              if (windowRef.current && !windowRef.current.closed) {
                windowRef.current.close();
              }
              windowRef.current = null;
              onReattach();
            }}
            className="btn-ghost text-accent-blue"
          >
            Reattach
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full">
      {/* Undock button */}
      <button
        onClick={handleDetach}
        title="Undock reader (Cmd+U)"
        className="absolute top-2 right-2 z-10 btn-ghost text-xs"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="inline mr-1">
          <path d="M7 1h4v4M11 1L6 6M5 1H2a1 1 0 00-1 1v8a1 1 0 001 1h8a1 1 0 001-1V7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Undock
      </button>
      {children}
    </div>
  );
}

/**
 * Hook for the detached window to receive navigation commands.
 */
export function useDetachedReaderReceiver(
  onNavigate: (linkId: string) => void
) {
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (event) => {
      if (event.data?.type === "navigate" && event.data.linkId) {
        onNavigate(event.data.linkId);
      }
    };
    return () => channel.close();
  }, [onNavigate]);
}
