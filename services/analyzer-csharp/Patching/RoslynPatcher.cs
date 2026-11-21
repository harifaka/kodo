using Kodo.Analyzer.CSharp.Models;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Kodo.Analyzer.CSharp.Patching;

/// <summary>
/// Stateless dry-run patcher. Parses the supplied text with Roslyn and rewrites only the targeted
/// members/attributes. The original file on disk is never opened, and the result is returned as text.
/// </summary>
public static class RoslynPatcher
{
    public static PatchResponse Patch(PatchRequest? request)
    {
        var content = request?.Content ?? string.Empty;
        var applied = new List<string>();
        var warnings = new List<string>();

        if (request is null)
        {
            warnings.Add("Request body is required.");
            return new PatchResponse(content, applied, warnings);
        }

        if (string.IsNullOrWhiteSpace(content))
        {
            warnings.Add("Content is empty; there is nothing to patch.");
            return new PatchResponse(content, applied, warnings);
        }

        if (request.Operations is null || request.Operations.Count == 0)
        {
            return new PatchResponse(content, applied, warnings);
        }

        var tree = CSharpSyntaxTree.ParseText(
            content,
            new CSharpParseOptions(LanguageVersion.Latest),
            path: request.FilePath ?? string.Empty);

        if (tree.GetDiagnostics().Any(diagnostic => diagnostic.Severity == DiagnosticSeverity.Error))
        {
            warnings.Add("The file has parse errors; Roslyn applied best-effort edits inside recoverable syntax.");
        }

        SyntaxNode root = tree.GetRoot();
        var eol = PatchSyntax.LineEnding(root);

        foreach (var operation in request.Operations)
        {
            if (operation is null || string.IsNullOrWhiteSpace(operation.Op))
            {
                warnings.Add("An operation was missing 'op'; it was skipped.");
                continue;
            }

            try
            {
                root = Apply(root, operation, applied, warnings, eol);
            }
            catch (Exception ex)
            {
                warnings.Add($"{operation.Op}: {ex.Message}");
            }
        }

        return new PatchResponse(root.ToFullString(), applied, warnings);
    }

    private static SyntaxNode Apply(
        SyntaxNode root,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings,
        string eol)
    {
        var typeName = PatchSyntax.SimpleName(operation.TypeName);
        if (typeName.Length == 0)
        {
            warnings.Add($"{operation.Op}: typeName is required; operation skipped.");
            return root;
        }

        var declaration = PatchSyntax.FindType(root, typeName);
        if (declaration is null)
        {
            warnings.Add($"{operation.Op}: type '{typeName}' was not found in this file; operation skipped.");
            return root;
        }

        return operation.Op switch
        {
            "add_field" => AddField(root, declaration, operation, applied, warnings, eol, dependency: false),
            "add_dependency" => AddField(root, declaration, operation, applied, warnings, eol, dependency: true),
            "update_field" => UpdateField(root, declaration, operation, applied, warnings, eol),
            "remove_field" or "remove_dependency" => RemoveField(root, declaration, operation, applied, warnings, eol),
            "add_annotation" => AddAnnotation(root, declaration, operation, applied, warnings, eol),
            "remove_annotation" => RemoveAnnotation(root, declaration, operation, applied, warnings),
            _ => Unknown(root, operation, warnings),
        };
    }

    private static SyntaxNode Unknown(SyntaxNode root, PatchOperation operation, List<string> warnings)
    {
        warnings.Add($"Unsupported operation '{operation.Op}'.");
        return root;
    }

    private static SyntaxNode AddField(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings,
        string eol,
        bool dependency)
    {
        var field = operation.Field;
        if (field is null || string.IsNullOrWhiteSpace(field.Name))
        {
            warnings.Add($"{operation.Op}: field details are required; operation skipped.");
            return root;
        }

        if (declaration is not TypeDeclarationSyntax typeDeclaration)
        {
            warnings.Add($"{operation.Op}: enum members cannot be added as fields.");
            return root;
        }

        if (typeDeclaration.OpenBraceToken.RawKind == 0)
        {
            warnings.Add(
                $"{operation.Op}: '{typeDeclaration.Identifier.ValueText}' has no body " +
                "(positional record without braces); add a body before inserting members.");
            return root;
        }

        if (FindMember(declaration, field.Name) is not null)
        {
            warnings.Add($"{operation.Op}: member '{field.Name}' already exists.");
            return root;
        }

        var indent = PatchSyntax.MemberIndent(declaration);
        var lines = new List<string>();
        foreach (var annotation in field.Annotations)
        {
            var normalized = PatchSyntax.NormalizeAttribute(annotation);
            if (normalized.Length > 0)
            {
                lines.Add(normalized);
            }
        }

        var modifiers = PatchSyntax.ModifierText(field.Visibility ?? (dependency ? "private" : null));
        var typeText = string.IsNullOrWhiteSpace(field.Type) ? "object" : field.Type.Trim();
        lines.Add(declaration is InterfaceDeclarationSyntax
            ? $"{modifiers}{typeText} {field.Name.Trim()} {{ get; set; }}"
            : $"{modifiers}{typeText} {field.Name.Trim()};");

        var member = PatchSyntax.ParseMember(lines, indent, eol);
        if (member is null)
        {
            warnings.Add($"{operation.Op}: could not parse a member for '{field.Name}'.");
            return root;
        }

        var updated = PatchSyntax.AddMember(typeDeclaration, member, indent, eol);
        root = root.ReplaceNode(declaration, updated);
        applied.Add($"{operation.Op} {typeDeclaration.Identifier.ValueText}.{field.Name.Trim()}");

        if (dependency)
        {
            warnings.Add(
                $"Dependency '{field.Name.Trim()}' was added as a member; constructor/setter injection must be wired by hand.");
        }

        return PatchSyntax.AddUsings(root, PatchSyntax.UsingsFor(field, null), eol);
    }

    private static SyntaxNode UpdateField(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings,
        string eol)
    {
        var field = operation.Field;
        if (field is null || string.IsNullOrWhiteSpace(field.Name))
        {
            warnings.Add("update_field: field details are required; operation skipped.");
            return root;
        }

        var originalName = operation.OriginalName ?? operation.FieldName ?? field.Name;
        var member = FindMember(declaration, originalName);
        if (member is null)
        {
            warnings.Add($"update_field: member '{originalName}' was not found.");
            return root;
        }

        if (declaration is not TypeDeclarationSyntax typeDeclaration)
        {
            return root;
        }

        var indent = PatchSyntax.MemberIndent(declaration);
        MemberDeclarationSyntax? replacement = member switch
        {
            FieldDeclarationSyntax fieldDeclaration => PatchSyntax.RebuildField(
                fieldDeclaration,
                originalName,
                field.Name.Trim(),
                field.Type,
                field.Visibility,
                field.Annotations,
                indent,
                eol),
            PropertyDeclarationSyntax property => PatchSyntax.RebuildProperty(
                property,
                field.Name.Trim(),
                field.Type,
                field.Visibility,
                field.Annotations,
                indent,
                eol),
            _ => null,
        };

        if (replacement is null)
        {
            warnings.Add($"update_field: could not rebuild '{originalName}'.");
            return root;
        }

        var updated = (BaseTypeDeclarationSyntax)typeDeclaration.ReplaceNode(member, replacement);
        root = root.ReplaceNode(declaration, updated);
        applied.Add($"update_field {typeDeclaration.Identifier.ValueText}.{field.Name.Trim()}");

        if (!string.Equals(originalName, field.Name.Trim(), StringComparison.Ordinal))
        {
            var renamedType = PatchSyntax.FindType(root, typeDeclaration.Identifier.ValueText);
            if (renamedType is not null)
            {
                var renamer = new IdentifierRenamer(originalName, field.Name.Trim());
                if (renamer.Visit(renamedType) is BaseTypeDeclarationSyntax renamed)
                {
                    root = root.ReplaceNode(renamedType, renamed);
                    if (renamer.Count > 0)
                    {
                        warnings.Add(
                            $"Renamed {renamer.Count} reference(s) from '{originalName}' to '{field.Name.Trim()}'; review the diff.");
                    }
                }
            }
        }

        return PatchSyntax.AddUsings(root, PatchSyntax.UsingsFor(field, null), eol);
    }

    private static SyntaxNode RemoveField(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings,
        string eol)
    {
        var name = operation.FieldName ?? operation.Field?.Name;
        if (string.IsNullOrWhiteSpace(name))
        {
            warnings.Add($"{operation.Op}: fieldName is required; operation skipped.");
            return root;
        }

        var member = FindMember(declaration, name);
        if (member is null)
        {
            warnings.Add($"{operation.Op}: member '{name}' was not found.");
            return root;
        }

        if (declaration is not TypeDeclarationSyntax typeDeclaration)
        {
            return root;
        }

        if (member is FieldDeclarationSyntax field && field.Declaration.Variables.Count > 1)
        {
            var remaining = field.Declaration.Variables
                .Where(variable => !string.Equals(variable.Identifier.ValueText, name, StringComparison.Ordinal))
                .ToArray();
            var indent = PatchSyntax.MemberIndent(declaration);
            var lines = field.AttributeLists.Select(list => list.ToString()).ToList();
            var modifiers = PatchSyntax.OriginalModifierText(field.Modifiers);
            lines.Add(
                $"{modifiers}{field.Declaration.Type} {string.Join(", ", remaining.Select(variable => variable.ToString()))};");

            if (PatchSyntax.ParseMember(lines, indent, eol) is not FieldDeclarationSyntax rebuilt)
            {
                warnings.Add($"{operation.Op}: could not rebuild the multi-variable field '{name}'.");
                return root;
            }

            var replaced = (BaseTypeDeclarationSyntax)typeDeclaration.ReplaceNode(
                field,
                PatchSyntax.WithOriginalTrivia(rebuilt, field));
            root = root.ReplaceNode(declaration, replaced);
        }
        else
        {
            if (typeDeclaration.RemoveNode(member, SyntaxRemoveOptions.KeepNoTrivia) is not TypeDeclarationSyntax updated)
            {
                warnings.Add($"{operation.Op}: could not remove '{name}'.");
                return root;
            }

            root = root.ReplaceNode(declaration, updated);
        }

        applied.Add($"{operation.Op} {typeDeclaration.Identifier.ValueText}.{name}");

        var updatedType = PatchSyntax.FindType(root, typeDeclaration.Identifier.ValueText);
        if (updatedType is not null)
        {
            var remainingReferences = updatedType.DescendantNodes()
                .OfType<IdentifierNameSyntax>()
                .Count(node => string.Equals(node.Identifier.ValueText, name, StringComparison.Ordinal));
            if (remainingReferences > 0)
            {
                warnings.Add(
                    $"Field '{name}' is still referenced {remainingReferences} time(s) inside " +
                    $"'{typeDeclaration.Identifier.ValueText}'; update those references by hand.");
            }
        }

        return root;
    }

    private static SyntaxNode AddAnnotation(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings,
        string eol)
    {
        var attributeList = PatchSyntax.ParseAttributeList(operation.Annotation);
        var name = PatchSyntax.AttributeNameFromText(operation.Annotation);
        if (attributeList is null || name.Length == 0)
        {
            warnings.Add("add_annotation: annotation is required.");
            return root;
        }

        SyntaxNode target = declaration;
        if (!string.IsNullOrWhiteSpace(operation.FieldName))
        {
            target = FindMember(declaration, operation.FieldName) ?? declaration;
            if (target == declaration)
            {
                warnings.Add($"add_annotation: member '{operation.FieldName}' was not found.");
                return root;
            }
        }

        if (PatchSyntax.HasAttribute(target, name))
        {
            warnings.Add($"add_annotation: {operation.Annotation} is already present.");
            return root;
        }

        var indent = ReferenceEquals(target, declaration)
            ? PatchSyntax.TypeIndent(declaration)
            : PatchSyntax.MemberIndent(declaration);
        var updated = PatchSyntax.AddAttributeList(target, attributeList, indent, eol);
        root = ReplaceTarget(root, declaration, target, updated);
        applied.Add($"add_annotation {declaration.Identifier.ValueText} {operation.Annotation}");
        return PatchSyntax.AddUsings(root, PatchSyntax.UsingsFor(null, operation.Annotation), eol);
    }

    private static SyntaxNode RemoveAnnotation(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        PatchOperation operation,
        List<string> applied,
        List<string> warnings)
    {
        var name = PatchSyntax.AttributeNameFromText(operation.Annotation);
        if (name.Length == 0)
        {
            warnings.Add("remove_annotation: annotation is required.");
            return root;
        }

        SyntaxNode target = declaration;
        if (!string.IsNullOrWhiteSpace(operation.FieldName))
        {
            target = FindMember(declaration, operation.FieldName) ?? declaration;
            if (target == declaration)
            {
                warnings.Add($"remove_annotation: member '{operation.FieldName}' was not found.");
                return root;
            }
        }

        if (!PatchSyntax.HasAttribute(target, name))
        {
            warnings.Add($"remove_annotation: {operation.Annotation} was not found.");
            return root;
        }

        var (updated, removed) = PatchSyntax.RemoveAttribute(target, name);
        if (!removed)
        {
            warnings.Add($"remove_annotation: {operation.Annotation} was not found.");
            return root;
        }

        root = ReplaceTarget(root, declaration, target, updated);
        applied.Add($"remove_annotation {declaration.Identifier.ValueText} {operation.Annotation}");
        return root;
    }

    private static SyntaxNode ReplaceTarget(
        SyntaxNode root,
        BaseTypeDeclarationSyntax declaration,
        SyntaxNode target,
        SyntaxNode updatedTarget)
    {
        if (ReferenceEquals(target, declaration))
        {
            return updatedTarget is BaseTypeDeclarationSyntax updatedType
                ? root.ReplaceNode(declaration, updatedType)
                : root;
        }

        if (declaration.ReplaceNode(target, updatedTarget) is BaseTypeDeclarationSyntax updatedDeclaration)
        {
            return root.ReplaceNode(declaration, updatedDeclaration);
        }

        return root;
    }

    private static MemberDeclarationSyntax? FindMember(BaseTypeDeclarationSyntax declaration, string name)
    {
        if (declaration is not TypeDeclarationSyntax type)
        {
            return null;
        }

        foreach (var member in type.Members)
        {
            if (member is FieldDeclarationSyntax field &&
                field.Declaration.Variables.Any(variable =>
                    string.Equals(variable.Identifier.ValueText, name, StringComparison.Ordinal)))
            {
                return member;
            }

            if (member is PropertyDeclarationSyntax property &&
                string.Equals(property.Identifier.ValueText, name, StringComparison.Ordinal))
            {
                return member;
            }
        }

        return null;
    }

    private sealed class IdentifierRenamer : CSharpSyntaxRewriter
    {
        private readonly string _oldName;
        private readonly string _newName;

        public IdentifierRenamer(string oldName, string newName)
        {
            _oldName = oldName;
            _newName = newName;
        }

        public int Count { get; private set; }

        public override SyntaxNode? VisitIdentifierName(IdentifierNameSyntax node)
        {
            if (string.Equals(node.Identifier.ValueText, _oldName, StringComparison.Ordinal))
            {
                Count++;
                return node.WithIdentifier(
                    SyntaxFactory.Identifier(_newName).WithTriviaFrom(node.Identifier));
            }

            return base.VisitIdentifierName(node);
        }
    }
}
