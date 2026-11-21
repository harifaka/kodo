using System.Text.Json;
using Kodo.Analyzer.CSharp.Analysis;
using Kodo.Analyzer.CSharp.Models;
using Kodo.Analyzer.CSharp.Patching;

var builder = WebApplication.CreateBuilder(args);

// KODO_CSHARP_URL pins the bind address for local `dotnet run`; otherwise ASPNETCORE_URLS
// (http://+:5050 in the container) wins and a plain localhost bind is the fallback.
var pinnedUrl = Environment.GetEnvironmentVariable("KODO_CSHARP_URL");
if (!string.IsNullOrWhiteSpace(pinnedUrl))
{
    builder.WebHost.UseUrls(pinnedUrl);
}
else if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ASPNETCORE_URLS")))
{
    builder.WebHost.UseUrls("http://localhost:5050");
}

// Stateless analysis ships every file's content in a single JSON body.
builder.WebHost.ConfigureKestrel(options => options.Limits.MaxRequestBodySize = 128 * 1024 * 1024);

builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
    options.SerializerOptions.DictionaryKeyPolicy = JsonNamingPolicy.CamelCase;
});

var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { status = "ok" }));
app.MapGet("/", () => Results.Ok(new
{
    service = "kodo-analyzer-csharp",
    status = "ok",
    endpoints = new[] { "GET /health", "POST /analyze", "POST /patch" }
}));

app.MapPost("/analyze", (AnalyzeRequest request) =>
{
    if (string.IsNullOrWhiteSpace(request?.RootPath))
    {
        return Results.BadRequest(new { error = "rootPath is required." });
    }

    if (request.Files is null || request.Files.Count == 0)
    {
        return Results.Ok(new AnalyzeResponse([], [], ["C# analyzer: no .cs files were provided."]));
    }

    try
    {
        var result = RoslynAnalyzer.Analyze(request.Files);
        return Results.Ok(new AnalyzeResponse(result.Nodes, result.Relations, result.Warnings));
    }
    catch (Exception ex)
    {
        return Results.Problem(
            title: "C# analysis failed",
            detail: ex.Message,
            statusCode: StatusCodes.Status500InternalServerError);
    }
});

// Dry-run only: the caller ships the file text, Roslyn returns proposed text, nothing is written.
app.MapPost("/patch", (PatchRequest request) =>
{
    if (request is null || request.Content is null)
    {
        return Results.BadRequest(new { error = "content is required." });
    }

    try
    {
        var result = RoslynPatcher.Patch(request);
        return Results.Ok(result);
    }
    catch (Exception ex)
    {
        return Results.Problem(
            title: "C# patch failed",
            detail: ex.Message,
            statusCode: StatusCodes.Status500InternalServerError);
    }
});

app.Run();
