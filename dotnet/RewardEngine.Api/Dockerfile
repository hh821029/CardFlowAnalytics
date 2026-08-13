# Build Stage (.NET 10 SDK)
FROM mcr.microsoft.com/dotnet/sdk:10.0-preview AS build
WORKDIR /src

# Copy csproj files and restore dependencies
COPY ["RewardEngine.Api/RewardEngine.Api.csproj", "RewardEngine.Api/"]
COPY ["RewardEngine.Core/RewardEngine.Core.csproj", "RewardEngine.Core/"]
RUN dotnet restore "RewardEngine.Api/RewardEngine.Api.csproj"

# Copy source code and build
COPY . .
WORKDIR "/src/RewardEngine.Api"
RUN dotnet publish "RewardEngine.Api.csproj" -c Release -o /app/publish /p:UseAppHost=false

# Runtime Stage (.NET 10 ASP.NET Core Runtime)
FROM mcr.microsoft.com/dotnet/aspnet:10.0-preview AS final
WORKDIR /app
COPY --from=build /app/publish .

ENV ASPNETCORE_URLS=http://+:5000
EXPOSE 5000

ENTRYPOINT ["dotnet", "RewardEngine.Api.dll"]
