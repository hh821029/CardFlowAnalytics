using RewardEngine.Api.Services;

var builder = WebApplication.CreateBuilder(args);

// ── 綁定 Listening URL (0.0.0.0 相容容器內部與外部連線) ────────────────────────
builder.WebHost.UseUrls("http://0.0.0.0:5000");

// ── DI 服務註冊 ──────────────────────────────────────────────────────────────
builder.Services.AddScoped<RewardsApiService>();

// ── CORS（對應 Python: app.add_middleware(CORSMiddleware, allow_origins=["*"])）
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.AllowAnyOrigin()
              .AllowAnyHeader()
              .AllowAnyMethod());
});

var app = builder.Build();

app.UseCors();

// ── 靜態檔案（對應 Python: app.mount("/", StaticFiles(directory="web"))）
var webDir = Path.Combine(builder.Environment.ContentRootPath, "..", "..", "web");
if (Directory.Exists(webDir))
{
    app.UseDefaultFiles(new DefaultFilesOptions
    {
        FileProvider = new Microsoft.Extensions.FileProviders.PhysicalFileProvider(
            Path.GetFullPath(webDir))
    });
    app.UseStaticFiles(new StaticFileOptions
    {
        FileProvider = new Microsoft.Extensions.FileProviders.PhysicalFileProvider(
            Path.GetFullPath(webDir))
    });
}

// ════════════════════════════════════════════════════════════════════════════
//  /api/run/rewards — ✅ 已實作（對應 Python api_run_rewards）
//  Query params 對應 Python 版本完全一致
// ════════════════════════════════════════════════════════════════════════════
app.MapGet("/api/run/rewards", async (
    HttpContext ctx,
    RewardsApiService svc,
    string? banks = null,
    string? cards = null,
    string? payments = null,
    string? time_window = null,
    string? start_date = null,
    string? end_date = null,
    string? location = null,
    bool enable_billing_validation = true,
    bool limit_by_card_start = false) =>
{
    var bankList   = banks?.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).ToList();
    var cardList   = cards?.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).ToList();
    var payList    = payments?.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0).ToList();

    ctx.Response.ContentType = "text/event-stream";
    ctx.Response.Headers.CacheControl = "no-cache";
    ctx.Response.Headers.Connection   = "keep-alive";

    await foreach (var msg in svc.RunRewardsAsync(
        bankList, cardList, payList,
        time_window, start_date, end_date, location,
        enable_billing_validation, limit_by_card_start,
        ctx.RequestAborted))
    {
        await ctx.Response.WriteAsync(msg, ctx.RequestAborted);
        await ctx.Response.Body.FlushAsync(ctx.RequestAborted);
    }
});

// ════════════════════════════════════════════════════════════════════════════
//  以下端點對應 Python server.py，但功能尚未在 .NET 實作
//  統一回傳 501 Not Implemented，保持 API 介面完整對應
// ════════════════════════════════════════════════════════════════════════════

/// <summary>回傳 501 Not Implemented，含任務說明（對應 Python 各 SSE 端點格式）</summary>
static IResult NotImplementedSse(string taskName) =>
    Results.Content(
        $"data: ❌ [尚未實作] '{taskName}' 功能目前僅在 Python 服務提供，.NET 版本尚未實作。\n\n",
        contentType: "text/event-stream",
        statusCode: 501);

// /api/run/etl — 對應 Python api_run_etl
app.MapGet("/api/run/etl", () => NotImplementedSse("ETL 流程"));

// /api/run/config_all — 對應 Python api_run_all_config_sync
app.MapGet("/api/run/config_all", () => NotImplementedSse("所有資料同步"));

// /api/run/config_card — 對應 Python api_run_config_card
app.MapGet("/api/run/config_card", () => NotImplementedSse("信用卡資料同步"));

// /api/run/config_reward — 對應 Python api_run_config_reward
app.MapGet("/api/run/config_reward", () => NotImplementedSse("回饋規則同步"));

// /api/run/config_mer — 對應 Python api_run_config_mer
app.MapGet("/api/run/config_mer", () => NotImplementedSse("特約商店同步"));

// /api/run/config_paygate — 對應 Python api_run_config_paygate
app.MapGet("/api/run/config_paygate", () => NotImplementedSse("支付平台同步"));

// /api/run/config_billing_history — 對應 Python api_run_config_billing_history
app.MapGet("/api/run/config_billing_history", () => NotImplementedSse("對帳單歷史同步"));

// /api/run/config_fx_table — 對應 Python api_run_config_fx_table
app.MapGet("/api/run/config_fx_table", () => NotImplementedSse("匯率每日表同步"));

// /api/run/analytics — 對應 Python api_run_analytics (RFM 分析)
app.MapGet("/api/run/analytics", () => NotImplementedSse("RFM 分析"));

// /api/run/query_export — 對應 Python api_run_query_export
app.MapGet("/api/run/query_export", () => NotImplementedSse("SQL 篩選與匯出"));

// ════════════════════════════════════════════════════════════════════════════
//  /api/analyzable-data — 回傳可分析資料骨架（對應 Python api_get_analyzable_data）
//  ⚠️ 目前回傳靜態空骨架，待對接 SQLite 查詢後補全
// ════════════════════════════════════════════════════════════════════════════
app.MapGet("/api/analyzable-data", () =>
    Results.Ok(new
    {
        banks             = Array.Empty<string>(),
        cards             = Array.Empty<string>(),
        payment_processes = Array.Empty<string>(),
        note              = "TODO: 此端點尚未對接 SQLite，回傳空骨架。"
    }));

// ── 根路徑健康確認（無 web/ 時的 fallback）
app.MapGet("/", () => Results.Ok(new
{
    message = "RewardEngine.Api is running.",
    version = "1.0.0"
}));

app.Run();
