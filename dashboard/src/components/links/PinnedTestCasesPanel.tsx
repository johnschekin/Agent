"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import {
  useRulePins,
  useCreatePinMutation,
  useDeletePinMutation,
  useEvaluatePinsMutation,
} from "@/lib/queries";

interface PinnedTestCasesPanelProps {
  ruleId: string;
  onClose: () => void;
}

export function PinnedTestCasesPanel({ ruleId, onClose }: PinnedTestCasesPanelProps) {
  const [activeTab, setActiveTab] = useState<"tp" | "tn">("tp");
  const [showAddForm, setShowAddForm] = useState(false);
  const [formDocId, setFormDocId] = useState("");
  const [formSectionNumber, setFormSectionNumber] = useState("");
  const [formNote, setFormNote] = useState("");

  const { data: pinsData, isLoading } = useRulePins(ruleId);
  const createPinMut = useCreatePinMutation();
  const deletePinMut = useDeletePinMutation();
  const evaluateMut = useEvaluatePinsMutation();

  const pins = pinsData?.pins ?? [];
  const filteredPins = pins.filter((p) =>
    activeTab === "tp" ? p.expected_verdict === "true_positive" : p.expected_verdict === "true_negative",
  );

  const evalResults = evaluateMut.data?.evaluations ?? [];

  // Escape to close — matches every other overlay in the system
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleAddPin = useCallback(() => {
    if (!formDocId.trim() || !formSectionNumber.trim()) return;
    createPinMut.mutate(
      {
        ruleId,
        data: {
          doc_id: formDocId.trim(),
          section_number: formSectionNumber.trim(),
          expected_verdict: activeTab === "tp" ? "true_positive" : "true_negative",
          note: formNote.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          setFormDocId("");
          setFormSectionNumber("");
          setFormNote("");
          setShowAddForm(false);
        },
      },
    );
  }, [ruleId, formDocId, formSectionNumber, formNote, activeTab, createPinMut]);

  const getPinEvalResult = (pinId: string) => {
    return evalResults.find((r: { pin_id: string }) => r.pin_id === pinId);
  };

  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-surface-1 border-l border-border shadow-overlay z-40 flex flex-col"
      data-testid="pinned-test-cases-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Pinned Test Cases</h3>
          <p className="text-xs text-text-muted mt-0.5">Rule: {ruleId}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors text-lg leading-none"
          data-testid="pins-panel-close"
        >
          &times;
        </button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-0 px-4 border-b border-border">
        <button
          type="button"
          onClick={() => setActiveTab("tp")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            activeTab === "tp"
              ? "text-accent-green border-b-accent-green"
              : "text-text-muted hover:text-text-primary border-b-transparent",
          )}
          data-testid="pins-tab-tp"
        >
          True Positives ({pins.filter((p) => p.expected_verdict === "true_positive").length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("tn")}
          className={cn(
            "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
            activeTab === "tn"
              ? "text-accent-red border-b-accent-red"
              : "text-text-muted hover:text-text-primary border-b-transparent",
          )}
          data-testid="pins-tab-tn"
        >
          True Negatives ({pins.filter((p) => p.expected_verdict === "true_negative").length})
        </button>
      </div>

      {/* Evaluate button */}
      <div className="px-4 py-2 border-b border-border">
        <button
          type="button"
          onClick={() => evaluateMut.mutate(ruleId)}
          disabled={evaluateMut.isPending || pins.length === 0}
          className="w-full px-3 py-1.5 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          data-testid="evaluate-pins-btn"
        >
          {evaluateMut.isPending ? "Evaluating..." : "Evaluate All Pins"}
        </button>
      </div>

      {/* Pins list */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-2">
        {isLoading ? (
          <p className="text-sm text-text-muted py-6 text-center">Loading pins...</p>
        ) : filteredPins.length === 0 ? (
          <p className="text-sm text-text-muted py-6 text-center">
            No {activeTab === "tp" ? "true positive" : "true negative"} pins
          </p>
        ) : (
          filteredPins.map((pin) => {
            const evalResult = getPinEvalResult(pin.pin_id);
            return (
              <div
                key={pin.pin_id}
                className="flex items-start justify-between px-3 py-2 bg-surface-2 rounded-lg"
                data-testid={`pin-${pin.pin_id}`}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-mono text-text-primary truncate">
                    {pin.doc_id}
                  </p>
                  <p className="text-xs text-text-muted">
                    Section {pin.section_number}
                  </p>
                  {pin.note && (
                    <p className="text-xs text-text-secondary mt-0.5 truncate">
                      {pin.note}
                    </p>
                  )}
                  {evalResult && (
                    <Badge
                      variant={evalResult.passed ? "green" : "red"}
                      className="mt-1"
                      data-testid={`pin-result-${pin.pin_id}`}
                    >
                      {evalResult.passed ? "PASS" : "FAIL"}
                    </Badge>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => deletePinMut.mutate({ ruleId, pinId: pin.pin_id })}
                  disabled={deletePinMut.isPending}
                  className="text-text-muted hover:text-accent-red transition-colors ml-2 text-xs"
                  data-testid={`delete-pin-${pin.pin_id}`}
                >
                  &times;
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Add pin form */}
      <div className="px-4 py-3 border-t border-border">
        {showAddForm ? (
          <div className="space-y-2">
            <input
              type="text"
              value={formDocId}
              onChange={(e) => setFormDocId(e.target.value)}
              placeholder="Doc ID"
              className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
              data-testid="pin-form-doc-id"
            />
            <input
              type="text"
              value={formSectionNumber}
              onChange={(e) => setFormSectionNumber(e.target.value)}
              placeholder="Section number"
              className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
              data-testid="pin-form-section"
            />
            <input
              type="text"
              value={formNote}
              onChange={(e) => setFormNote(e.target.value)}
              placeholder="Note (optional)"
              className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
              data-testid="pin-form-note"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleAddPin}
                disabled={createPinMut.isPending || !formDocId.trim() || !formSectionNumber.trim()}
                className="flex-1 px-3 py-1.5 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 disabled:opacity-50"
                data-testid="pin-form-submit"
              >
                {createPinMut.isPending ? "Adding..." : "Add Pin"}
              </button>
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowAddForm(true)}
            className="w-full px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg hover:text-text-primary transition-colors"
            data-testid="add-pin-btn"
          >
            + Add Pin
          </button>
        )}
      </div>
    </div>
  );
}
