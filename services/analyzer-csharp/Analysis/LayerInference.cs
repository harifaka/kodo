using Kodo.Analyzer.CSharp.Models;

namespace Kodo.Analyzer.CSharp.Analysis;

/// <summary>
/// Heuristic (syntax-only) layer inference for .NET types. Roslyn's syntactic model has no
/// semantic resolution here, so we rely on naming conventions, attributes and file shape.
/// </summary>
public static class LayerInference
{
    private static readonly string[] ControllerAttributes = ["[ApiController]", "[Controller]", "[Route]"];
    private static readonly string[] EntityAttributes = ["[Table]", "[Key]", "[Column]"];

    public static string Infer(string name, string kind, string filePath, IReadOnlyList<string> annotations)
    {
        var normalizedPath = filePath.Replace('\\', '/');
        var hasAnnotation = (string[] candidates) =>
            annotations.Any(a => candidates.Contains(a, StringComparer.OrdinalIgnoreCase));

        // WPF / WinUI code-behind is a view regardless of type name.
        if (normalizedPath.EndsWith(".xaml.cs", StringComparison.OrdinalIgnoreCase) &&
            !name.EndsWith("ViewModel", StringComparison.OrdinalIgnoreCase))
        {
            return IrConstants.Layers.View;
        }

        if (name.EndsWith("Controller", StringComparison.OrdinalIgnoreCase) || hasAnnotation(ControllerAttributes))
        {
            return IrConstants.Layers.Controller;
        }

        if (name.EndsWith("ViewModel", StringComparison.OrdinalIgnoreCase))
        {
            return IrConstants.Layers.ViewModel;
        }

        if (name.EndsWith("Repository", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("Repo", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("Dao", StringComparison.OrdinalIgnoreCase))
        {
            return IrConstants.Layers.Repository;
        }

        if (name.EndsWith("Service", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("Manager", StringComparison.OrdinalIgnoreCase))
        {
            return IrConstants.Layers.Service;
        }

        if (kind == IrConstants.Kinds.Enum)
        {
            return IrConstants.Layers.Other;
        }

        if (name.EndsWith("Entity", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("DbSet", StringComparison.OrdinalIgnoreCase) ||
            hasAnnotation(EntityAttributes))
        {
            return IrConstants.Layers.Entity;
        }

        if (name.EndsWith("Window", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("Page", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("UserControl", StringComparison.OrdinalIgnoreCase) ||
            name.EndsWith("Dialog", StringComparison.OrdinalIgnoreCase))
        {
            return IrConstants.Layers.View;
        }

        return IrConstants.Layers.Other;
    }
}
