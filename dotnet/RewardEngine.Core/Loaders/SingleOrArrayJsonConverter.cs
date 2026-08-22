using System.Text.Json;
using System.Text.Json.Serialization;

namespace RewardEngine.Core.Loaders;

/// <summary>
/// 支援 JSON 中既可以是單一字串 (如 "統一超商") 也可以是字串陣列 (如 ["統一超商", "全家"]) 的相容反序列化器
/// </summary>
public class SingleOrArrayJsonConverter : JsonConverter<string[]>
{
    public override string[]? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null)
        {
            return null;
        }

        if (reader.TokenType == JsonTokenType.String)
        {
            var str = reader.GetString();
            return str == null ? null : [str];
        }

        if (reader.TokenType == JsonTokenType.StartArray)
        {
            var list = new List<string>();
            while (reader.Read())
            {
                if (reader.TokenType == JsonTokenType.EndArray)
                {
                    break;
                }

                if (reader.TokenType == JsonTokenType.String)
                {
                    var item = reader.GetString();
                    if (item != null)
                    {
                        list.Add(item);
                    }
                }
            }
            return list.ToArray();
        }

        throw new JsonException($"無法將 JSON Token '{reader.TokenType}' 轉換為 string[]。");
    }

    public override void Write(Utf8JsonWriter writer, string[]? value, JsonSerializerOptions options)
    {
        if (value == null)
        {
            writer.WriteNullValue();
            return;
        }

        if (value.Length == 1)
        {
            writer.WriteStringValue(value[0]);
        }
        else
        {
            writer.WriteStartArray();
            foreach (var item in value)
            {
                writer.WriteStringValue(item);
            }
            writer.WriteEndArray();
        }
    }
}
