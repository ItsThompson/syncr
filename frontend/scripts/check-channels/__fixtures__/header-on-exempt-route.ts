client.POST("/api/v1/weeks/{iso_week}/tradeoffs", {
  headers: idempotentHeaders(),
});
