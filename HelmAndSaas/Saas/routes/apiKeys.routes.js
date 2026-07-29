import { Router } from "express";
import { jwtAuth } from "../middleware/jwtAuth.js";
import { asyncRoute } from "../middleware/errorHandler.js";
import * as apiKeyService from "../services/apiKeyService.js";

export const apiKeysRouter = Router();
apiKeysRouter.use(jwtAuth);

apiKeysRouter.get(
  "/",
  asyncRoute(async (req, res) => {
    const keys = await apiKeyService.listApiKeys(req.tenantId);
    res.json({ api_keys: keys });
  })
);

apiKeysRouter.post(
  "/",
  asyncRoute(async (req, res) => {
    const { name } = req.body || {};
    const created = await apiKeyService.generateApiKey(req.tenantId, name);
    res.status(201).json(created);
  })
);

apiKeysRouter.delete(
  "/:id",
  asyncRoute(async (req, res) => {
    await apiKeyService.revokeApiKey(req.tenantId, req.params.id);
    res.status(204).send();
  })
);
