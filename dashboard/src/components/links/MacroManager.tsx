"use client";

import { useCallback, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import {
  useMacros,
  useCreateMacroMutation,
  useDeleteMacroMutation,
} from "@/lib/queries";

interface MacroManagerProps {
  familyFilter?: string;
  onInsertMacro?: (macroName: string) => void;
}

export function MacroManager({ familyFilter, onInsertMacro }: MacroManagerProps) {
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [editMacroName, setEditMacroName] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formAstJson, setFormAstJson] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const { data: macrosData, isLoading } = useMacros();
  const createMut = useCreateMacroMutation();
  const deleteMut = useDeleteMacroMutation();

  const macros = macrosData?.macros ?? [];
  const filteredMacros = familyFilter
    ? macros.filter((m) => !m.family_id || m.family_id === familyFilter)
    : macros;

  const resetForm = useCallback(() => {
    setFormName("");
    setFormDescription("");
    setFormAstJson("");
    setEditMacroName(null);
    setCreateFormOpen(false);
  }, []);

  const handleCreate = useCallback(() => {
    if (!formName.trim() || !formAstJson.trim()) return;
    createMut.mutate(
      {
        name: formName.trim(),
        description: formDescription.trim(),
        family_id: familyFilter,
        ast_json: formAstJson.trim(),
      },
      {
        onSuccess: () => {
          resetForm();
        },
      },
    );
  }, [formName, formDescription, formAstJson, familyFilter, createMut, resetForm]);

  const handleEdit = useCallback(
    (macroName: string) => {
      const macro = macros.find((m) => m.name === macroName);
      if (!macro) return;
      setEditMacroName(macroName);
      setFormName(macro.name);
      setFormDescription(macro.description);
      setFormAstJson(macro.ast_json);
      setCreateFormOpen(true);
    },
    [macros],
  );

  const handleCancelForm = useCallback(() => {
    resetForm();
  }, [resetForm]);

  const handleDelete = useCallback(
    (name: string) => {
      deleteMut.mutate(name, {
        onSuccess: () => setDeleteConfirm(null),
      });
    },
    [deleteMut],
  );

  const isEditing = editMacroName !== null;
  const formButtonLabel = isEditing
    ? createMut.isPending
      ? "Updating..."
      : "Update Macro"
    : createMut.isPending
      ? "Creating..."
      : "Create Macro";

  return (
    <div className="space-y-3" data-testid="macro-manager">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          Macros
        </h4>
        <button
          type="button"
          onClick={() => {
            if (createFormOpen) {
              handleCancelForm();
            } else {
              setCreateFormOpen(true);
            }
          }}
          className="text-xs text-accent-blue hover:underline"
          data-testid="create-macro-toggle"
        >
          {createFormOpen ? "Cancel" : "+ New Macro"}
        </button>
      </div>

      {/* Create / Edit form */}
      {createFormOpen && (
        <div className="space-y-2 p-3 bg-surface-2 rounded-lg border border-border" data-testid="macro-create-form">
          <input
            type="text"
            value={formName}
            onChange={(e) => setFormName(e.target.value)}
            placeholder="Macro name (without @)"
            disabled={isEditing}
            className={cn(
              "w-full bg-surface-1 border border-border rounded px-2 py-1.5 text-sm text-text-primary",
              isEditing && "opacity-60 cursor-not-allowed",
            )}
            data-testid="macro-form-name"
          />
          <input
            type="text"
            value={formDescription}
            onChange={(e) => setFormDescription(e.target.value)}
            placeholder="Description"
            className="w-full bg-surface-1 border border-border rounded px-2 py-1.5 text-sm text-text-primary"
            data-testid="macro-form-description"
          />
          <textarea
            value={formAstJson}
            onChange={(e) => setFormAstJson(e.target.value)}
            placeholder='AST JSON (e.g. {"op":"and","children":[...]})'
            className="w-full bg-surface-1 border border-border rounded px-2 py-1.5 text-sm text-text-primary resize-none h-20 font-mono"
            data-testid="macro-form-ast"
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={createMut.isPending || !formName.trim() || !formAstJson.trim()}
            className="w-full px-3 py-1.5 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 disabled:opacity-50"
            data-testid="macro-form-submit"
          >
            {formButtonLabel}
          </button>
        </div>
      )}

      {/* Macros list */}
      {isLoading ? (
        <p className="text-sm text-text-muted py-4 text-center">Loading macros...</p>
      ) : filteredMacros.length === 0 ? (
        <p className="text-sm text-text-muted py-4 text-center">No macros defined</p>
      ) : (
        <div className="space-y-1.5">
          {filteredMacros.map((macro) => {
            const usageCount = macro.usage_count ?? 0;
            return (
              <div
                key={macro.name}
                className="flex items-center justify-between px-3 py-2 bg-surface-2 rounded-lg"
                data-testid={`macro-${macro.name}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-accent-blue">@{macro.name}</span>
                    {macro.family_id && (
                      <Badge variant="default" className="text-[10px]">{macro.family_id}</Badge>
                    )}
                    <Badge
                      variant="default"
                      className="text-[10px]"
                      data-testid={`macro-usage-${macro.name}`}
                    >
                      {usageCount} {usageCount === 1 ? "rule" : "rules"}
                    </Badge>
                  </div>
                  <p className="text-xs text-text-muted truncate mt-0.5">
                    {macro.description}
                  </p>
                </div>
                <div className="flex items-center gap-2 ml-2">
                  {onInsertMacro && (
                    <button
                      type="button"
                      onClick={() => onInsertMacro(`@${macro.name}`)}
                      className="text-xs text-accent-blue hover:underline"
                      data-testid={`insert-macro-${macro.name}`}
                    >
                      Insert
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleEdit(macro.name)}
                    className="text-xs text-text-muted hover:text-accent-blue transition-colors"
                    data-testid={`edit-macro-${macro.name}`}
                  >
                    Edit
                  </button>
                  {deleteConfirm === macro.name ? (
                    <div className="flex items-center gap-1">
                      {usageCount > 0 && (
                        <span className="text-[10px] text-accent-red mr-1">
                          This macro is used by rules
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDelete(macro.name)}
                        className="text-xs text-accent-red hover:underline"
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm(null)}
                        className="text-xs text-text-muted hover:text-text-primary"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setDeleteConfirm(macro.name)}
                      className="text-xs text-text-muted hover:text-accent-red transition-colors"
                      data-testid={`delete-macro-${macro.name}`}
                    >
                      &times;
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
