import "dotenv/config";

export const config = {
  port: parseInt(process.env.PORT || "8000", 10),
  jwtAccessSecret: process.env.JWT_ACCESS_SECRET || "dev_access_secret",
  jwtRefreshSecret: process.env.JWT_REFRESH_SECRET || "dev_refresh_secret",
  accessTokenExpiry: process.env.ACCESS_TOKEN_EXPIRY || "15m",
  refreshTokenExpiryDays: parseRefreshDays(process.env.REFRESH_TOKEN_EXPIRY || "7d"),
  bcryptCost: parseInt(process.env.BCRYPT_COST || "12", 10),
  apiKeyCacheTtlSeconds: parseInt(process.env.API_KEY_CACHE_TTL_SECONDS || "300", 10),
  inferenceMode: process.env.INFERENCE_MODE || "stub",
  onnxModelPath: process.env.ONNX_MODEL_PATH || "./inference/model/sadmc_model.onnx",
};

function parseRefreshDays(value) {
  const match = /^(\d+)d$/.exec(value);
  return match ? parseInt(match[1], 10) : 7;
}
