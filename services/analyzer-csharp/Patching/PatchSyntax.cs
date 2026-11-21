using System.Text.RegularExpressions;
using Kodo.Analyzer.CSharp.Models;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Kodo.Analyzer.CSharp.Patching;

/// <summary>
/// Trivia-preserving syntax helpers. Every helper only touches the node it is given; untouched
/// methods, comments and formatting keep their original tokens and trivia.
/// </summary>
internal static class PatchSyntax
{
    private static readonly Regex IdentifierRegex = new("[A-Za-z_][A-Za-z0-9_]*", RegexOptions.Compiled);

    private static readonly Dictionary<string, string> UsingMap = new(StringComparer.Ordinal)
    {
        ["Required"] = "System.ComponentModel.DataAnnotations",
        ["StringLength"] = "System.ComponentModel.DataAnnotations",
        ["Key"] = "System.ComponentModel.DataAnnotations",
        ["Range"] = "System.ComponentModel.DataAnnotations",
        ["RegularExpression"] = "System.ComponentModel.DataAnnotations",
        ["EmailAddress"] = "System.ComponentModel.DataAnnotations",
        ["Phone"] = "System.ComponentModel.DataAnnotations",
        ["JsonPropertyName"] = "System.Text.Json.Serialization",
        ["JsonProperty"] = "System.Text.Json.Serialization",
        ["Table"] = "System.ComponentModel.DataAnnotations.Schema",
        ["Column"] = "System.ComponentModel.DataAnnotations.Schema",
        ["ForeignKey"] = "System.ComponentModel.DataAnnotations.Schema",
        ["NotMapped"] = "System.ComponentModel.DataAnnotations.Schema",
        ["List"] = "System.Collections.Generic",
        ["IList"] = "System.Collections.Generic",
        ["IEnumerable"] = "System.Collections.Generic",
        ["ICollection"] = "System.Collections.Generic",
        ["Dictionary"] = "System.Collections.Generic",
        ["HashSet"] = "System.Collections.Generic",
        ["Task"] = "System.Threading.Tasks",
    };

    public static string LineEnding(SyntaxNode root) =>
        root.SyntaxTree.GetText().ToString().Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";

    public static string TypeIndent(SyntaxNode node)
    {
        var text = node.SyntaxTree.GetText();
        var line = text.Lines.GetLineFromPosition(node.SpanStart);
        var column = Math.Clamp(node.SpanStart - line.Start, 0, line.Span.Length);
        var prefix = line.ToString()[..column];
        return prefix.All(ch => ch == ' ' || ch == '\t') ? prefix : string.Empty;
    }

    public static string MemberIndent(BaseTypeDeclarationSyntax declaration)
    {
        if (declaration is TypeDeclarationSyntax type && type.Members.Count > 0)
        {
            var trivia = type.Members[0].GetLeadingTrivia();
            for (var index = trivia.Count - 1; index >= 0; index--)
            {
                if (trivia[index].IsKind(SyntaxKind.WhitespaceTrivia))
                {
                    return trivia[index].ToString();
                }
                if (trivia[index].IsKind(SyntaxKind.EndOfLineTrivia))
                {
                    break;
                }
            }
        }

        return $"{TypeIndent(declaration)}    ";
    }

    public static string SimpleName(string? value)
    {
        var text = (value ?? string.Empty).Trim();
        var dot = text.LastIndexOf('.');
        return dot >= 0 ? text[(dot + 1)..].Trim() : text;
    }

    public static BaseTypeDeclarationSyntax? FindType(SyntaxNode root, string? typeName)
    {
        var simple = SimpleName(typeName);
        if (simple.Length == 0)
        {
            return null;
        }

        return root.DescendantNodes()
            .OfType<BaseTypeDeclarationSyntax>()
            .FirstOrDefault(node => string.Equals(node.Identifier.ValueText, simple, StringComparison.Ordinal));
    }

    public static MemberDeclarationSyntax? ParseMember(IEnumerable<string> lines, string indent, string eol)
    {
        var snippet = string.Join(eol, lines.Select(line => $"{indent}{line}"));
        return SyntaxFactory.ParseMemberDeclaration(snippet);
    }

    public static TypeDeclarationSyntax AddMember(
        TypeDeclarationSyntax declaration,
        MemberDeclarationSyntax member,
        string indent,
        string eol)
    {
        var previous = declaration.Members.LastOrDefault();
        var previousHasLineBreak = previous is null
            ? declaration.OpenBraceToken.TrailingTrivia.Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia))
            : previous.GetTrailingTrivia().Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia));

        var leading = new List<SyntaxTrivia>();
        if (!previousHasLineBreak)
        {
            leading.Add(SyntaxFactory.EndOfLine(eol));
        }
        leading.Add(SyntaxFactory.Whitespace(indent));

        // The close brace usually owns no newline of its own; give the appended member one unless it does.
        var closeBraceHasLineBreak = declaration.CloseBraceToken.LeadingTrivia
            .Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia));
        var trailing = closeBraceHasLineBreak
            ? SyntaxFactory.TriviaList()
            : SyntaxFactory.TriviaList(SyntaxFactory.EndOfLine(eol));

        var prepared = member
            .WithLeadingTrivia(SyntaxFactory.TriviaList(leading))
            .WithTrailingTrivia(trailing);
        return declaration.AddMembers(prepared);
    }

    public static MemberDeclarationSyntax WithOriginalTrivia(MemberDeclarationSyntax member, MemberDeclarationSyntax original) =>
        member
            .WithLeadingTrivia(original.GetLeadingTrivia())
            .WithTrailingTrivia(original.GetTrailingTrivia());

    public static string ModifierText(string? visibility)
    {
        if (string.IsNullOrWhiteSpace(visibility))
        {
            return string.Empty;
        }

        var allowed = new HashSet<string>(StringComparer.Ordinal)
        {
            "public", "private", "protected", "internal", "static", "readonly",
            "const", "virtual", "override", "required", "sealed", "abstract",
        };
        var words = visibility
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(word => allowed.Contains(word))
            .ToArray();
        return words.Length == 0 ? string.Empty : $"{string.Join(' ', words)} ";
    }

    public static string OriginalModifierText(SyntaxTokenList modifiers)
    {
        var words = modifiers
            .Select(token => token.Text)
            .Where(text => text.Length > 0)
            .ToArray();
        return words.Length == 0 ? string.Empty : $"{string.Join(' ', words)} ";
    }

    public static string NormalizeAttribute(string? annotation)
    {
        var text = (annotation ?? string.Empty).Trim();
        if (text.Length == 0)
        {
            return string.Empty;
        }

        if (text.StartsWith('@'))
        {
            text = text[1..].Trim();
        }
        if (!text.StartsWith('['))
        {
            text = $"[{text}";
        }
        if (!text.EndsWith(']'))
        {
            text = $"{text}]";
        }
        return text;
    }

    public static AttributeListSyntax? ParseAttributeList(string? annotation)
    {
        var normalized = NormalizeAttribute(annotation);
        if (normalized.Length == 0)
        {
            return null;
        }

        var unit = SyntaxFactory.ParseCompilationUnit($"{normalized}\ninternal class __KodoPatch {{ }}");
        return unit.DescendantNodes().OfType<AttributeListSyntax>().FirstOrDefault();
    }

    public static string AttributeNameFromText(string? value)
    {
        var text = (value ?? string.Empty).Trim();
        if (text.Length == 0)
        {
            return string.Empty;
        }
        text = text.TrimStart('@').TrimStart('[').TrimEnd(']');
        var paren = text.IndexOf('(');
        if (paren >= 0)
        {
            text = text[..paren];
        }
        var dot = text.LastIndexOf('.');
        if (dot >= 0)
        {
            text = text[(dot + 1)..];
        }
        text = text.Trim();
        return text.EndsWith("Attribute", StringComparison.Ordinal) ? text[..^"Attribute".Length] : text;
    }

    public static string AttributeName(NameSyntax name)
    {
        var text = name switch
        {
            QualifiedNameSyntax qualified => qualified.Right.Identifier.ValueText,
            AliasQualifiedNameSyntax alias => alias.Name.Identifier.ValueText,
            SimpleNameSyntax simple => simple.Identifier.ValueText,
            _ => name.ToString(),
        };
        text = text.Split('.').Last();
        return text.EndsWith("Attribute", StringComparison.Ordinal) ? text[..^"Attribute".Length] : text;
    }

    public static SyntaxList<AttributeListSyntax> GetAttributeLists(SyntaxNode node) => node switch
    {
        BaseTypeDeclarationSyntax type => type.AttributeLists,
        FieldDeclarationSyntax field => field.AttributeLists,
        PropertyDeclarationSyntax property => property.AttributeLists,
        _ => default,
    };

    public static SyntaxNode WithAttributeLists(SyntaxNode node, SyntaxList<AttributeListSyntax> lists) => node switch
    {
        BaseTypeDeclarationSyntax type => type.WithAttributeLists(lists),
        FieldDeclarationSyntax field => field.WithAttributeLists(lists),
        PropertyDeclarationSyntax property => property.WithAttributeLists(lists),
        _ => node,
    };

    public static bool HasAttribute(SyntaxNode node, string name) =>
        GetAttributeLists(node)
            .SelectMany(list => list.Attributes)
            .Any(attribute => string.Equals(AttributeName(attribute.Name), name, StringComparison.OrdinalIgnoreCase));

    public static SyntaxNode AddAttributeList(SyntaxNode node, AttributeListSyntax list, string indent, string eol)
    {
        var lists = GetAttributeLists(node);
        if (lists.Count == 0)
        {
            var leading = node.GetLeadingTrivia();
            var withoutLeading = node.WithoutLeadingTrivia();
            var first = list
                .WithLeadingTrivia(leading)
                .WithTrailingTrivia(SyntaxFactory.EndOfLine(eol), SyntaxFactory.Whitespace(indent));
            return WithAttributeLists(withoutLeading, SyntaxFactory.SingletonList(first));
        }

        var last = lists.Last();
        var lastEndsLine = last.GetTrailingTrivia().Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia));
        var followingToken = node.DescendantTokens()
            .FirstOrDefault(token => token.SpanStart >= last.Span.End);
        var followingHasLineBreak = followingToken.RawKind != 0 &&
            followingToken.LeadingTrivia.Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia));

        AttributeListSyntax appended;
        if (!lastEndsLine)
        {
            appended = list.WithLeadingTrivia(SyntaxFactory.Space);
        }
        else if (followingHasLineBreak)
        {
            appended = list;
        }
        else
        {
            // The following token already carries its indentation as leading trivia.
            appended = list.WithTrailingTrivia(SyntaxFactory.EndOfLine(eol));
        }

        return WithAttributeLists(node, lists.Add(appended));
    }

    public static (SyntaxNode Node, bool Removed) RemoveAttribute(SyntaxNode node, string name)
    {
        var lists = GetAttributeLists(node);
        var originalLeading = lists.Count > 0 ? lists[0].GetLeadingTrivia() : SyntaxFactory.TriviaList();
        var removed = false;
        var removedFirstList = false;
        var updated = new List<AttributeListSyntax>();

        foreach (var list in lists)
        {
            var remaining = list.Attributes
                .Where(attribute => !string.Equals(AttributeName(attribute.Name), name, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (remaining.Count == list.Attributes.Count)
            {
                updated.Add(list);
                continue;
            }

            removed = true;
            if (remaining.Count > 0)
            {
                updated.Add(list.WithAttributes(SyntaxFactory.SeparatedList(remaining)));
            }
            else if (updated.Count == 0)
            {
                removedFirstList = true;
            }
        }

        if (!removed)
        {
            return (node, false);
        }

        if (removedFirstList)
        {
            if (updated.Count > 0 && !updated[0].GetLeadingTrivia().Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia)))
            {
                updated[0] = updated[0].WithLeadingTrivia(originalLeading);
            }
            else if (updated.Count == 0)
            {
                var stripped = WithAttributeLists(node, default);
                return (stripped.WithLeadingTrivia(originalLeading), true);
            }
        }

        return (WithAttributeLists(node, SyntaxFactory.List(updated)), true);
    }

    public static SyntaxNode AddUsings(SyntaxNode root, IEnumerable<string> namespaces, string eol)
    {
        if (root is not CompilationUnitSyntax unit)
        {
            return root;
        }

        foreach (var ns in namespaces.Distinct(StringComparer.Ordinal))
        {
            if (unit.Usings.Any(existing => string.Equals(existing.Name?.ToString(), ns, StringComparison.Ordinal)))
            {
                continue;
            }

            var directive = SyntaxFactory.UsingDirective(SyntaxFactory.ParseName(ns))
                .WithUsingKeyword(
                    SyntaxFactory.Token(SyntaxKind.UsingKeyword).WithTrailingTrivia(SyntaxFactory.Space));

            if (unit.Usings.Count == 0)
            {
                unit = unit.AddUsings(directive.WithTrailingTrivia(SyntaxFactory.EndOfLine(eol)));
                continue;
            }

            var lastUsingEndsLine = unit.Usings.Last().GetTrailingTrivia()
                .Any(trivia => trivia.IsKind(SyntaxKind.EndOfLineTrivia));
            directive = lastUsingEndsLine
                ? directive.WithTrailingTrivia(SyntaxFactory.EndOfLine(eol))
                : directive
                    .WithLeadingTrivia(SyntaxFactory.EndOfLine(eol))
                    .WithTrailingTrivia(SyntaxFactory.EndOfLine(eol));
            unit = unit.AddUsings(directive);
        }

        return unit;
    }

    public static IEnumerable<string> UsingsFor(PatchField? field, string? annotation)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        if (field is not null)
        {
            foreach (var item in field.Annotations)
            {
                var name = AttributeNameFromText(item);
                if (name.Length > 0)
                {
                    names.Add(name);
                }
            }

            foreach (Match match in IdentifierRegex.Matches(field.Type ?? string.Empty))
            {
                names.Add(match.Value);
            }
        }

        var annotationName = AttributeNameFromText(annotation);
        if (annotationName.Length > 0)
        {
            names.Add(annotationName);
        }

        return names
            .Where(UsingMap.ContainsKey)
            .Select(name => UsingMap[name])
            .Distinct(StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();
    }

    public static FieldDeclarationSyntax? RebuildField(
        FieldDeclarationSyntax field,
        string oldName,
        string newName,
        string type,
        string? visibility,
        IReadOnlyList<string> annotations,
        string indent,
        string eol)
    {
        var lines = new List<string>();
        foreach (var annotation in annotations)
        {
            var normalized = NormalizeAttribute(annotation);
            if (normalized.Length > 0)
            {
                lines.Add(normalized);
            }
        }

        var modifiers = string.IsNullOrWhiteSpace(visibility)
            ? OriginalModifierText(field.Modifiers)
            : ModifierText(visibility);
        var typeText = string.IsNullOrWhiteSpace(type) ? field.Declaration.Type.ToString() : type.Trim();

        var variables = field.Declaration.Variables.Select(variable =>
        {
            var name = string.Equals(variable.Identifier.ValueText, oldName, StringComparison.Ordinal)
                ? newName
                : variable.Identifier.ValueText;
            var argumentList = variable.ArgumentList?.ToString() ?? string.Empty;
            var initializer = variable.Initializer is null ? string.Empty : $" = {variable.Initializer.Value}";
            return $"{name}{argumentList}{initializer}";
        });

        lines.Add($"{modifiers}{typeText} {string.Join(", ", variables)};");
        return ParseMember(lines, indent, eol) is FieldDeclarationSyntax updated
            ? WithOriginalTrivia(updated, field) as FieldDeclarationSyntax
            : null;
    }

    public static PropertyDeclarationSyntax? RebuildProperty(
        PropertyDeclarationSyntax property,
        string newName,
        string type,
        string? visibility,
        IReadOnlyList<string> annotations,
        string indent,
        string eol)
    {
        var lines = new List<string>();
        foreach (var annotation in annotations)
        {
            var normalized = NormalizeAttribute(annotation);
            if (normalized.Length > 0)
            {
                lines.Add(normalized);
            }
        }

        var modifiers = string.IsNullOrWhiteSpace(visibility)
            ? OriginalModifierText(property.Modifiers)
            : ModifierText(visibility);
        var typeText = string.IsNullOrWhiteSpace(type) ? property.Type.ToString() : type.Trim();

        string declaration;
        if (property.ExpressionBody is not null)
        {
            declaration = $"{modifiers}{typeText} {newName} => {property.ExpressionBody.Expression};";
        }
        else
        {
            var accessors = property.AccessorList?.ToString() ?? "{ get; set; }";
            var initializer = property.Initializer is null ? string.Empty : $"{property.Initializer};";
            declaration = $"{modifiers}{typeText} {newName} {accessors}{initializer}";
        }

        lines.Add(declaration);
        return ParseMember(lines, indent, eol) is PropertyDeclarationSyntax updated
            ? WithOriginalTrivia(updated, property) as PropertyDeclarationSyntax
            : null;
    }
}
