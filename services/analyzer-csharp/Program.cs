using System.Text.Json;
using Kodo.Analyzer.CSharp.Analysis;
using Kodo.Analyzer.CSharp.Models;

var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls(Environment.GetEnvironmentVariable("KODO_CSHARP_URL") ?? "http://localhost:5050");
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
    endpoints = new[] { "GET /health", "POST /analyze" }
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
        var result = RoslynAnalyzer.Analyze(request.RootPath, request.Files);
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

app.Run();
