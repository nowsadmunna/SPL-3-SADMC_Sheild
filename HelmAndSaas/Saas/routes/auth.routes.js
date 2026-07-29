import { Router } from "express";
import { asyncRoute } from "../middleware/errorHandler.js";
import * as authService from "../services/authService.js";

export const authRouter = Router();

authRouter.post(
  "/register",
  asyncRoute(async (req, res) => {
    const { organization_name, email, password } = req.body || {};
    if (!organization_name || !email || !password) {
      return res.status(400).json({ error: "organization_name, email, password are required" });
    }
    const tenant = await authService.registerTenant({
      organizationName: organization_name,
      email,
      password,
    });
    res.status(201).json({ tenant });
  })
);

authRouter.post(
  "/login",
  asyncRoute(async (req, res) => {
    const { email, password } = req.body || {};
    if (!email || !password) {
      return res.status(400).json({ error: "email and password are required" });
    }
    const result = await authService.login({ email, password });
    res.json(result);
  })
);

authRouter.post(
  "/refresh",
  asyncRoute(async (req, res) => {
    const { refresh_token } = req.body || {};
    if (!refresh_token) {
      return res.status(400).json({ error: "refresh_token is required" });
    }
    const result = await authService.refreshAccessToken(refresh_token);
    res.json(result);
  })
);

authRouter.post(
  "/logout",
  asyncRoute(async (req, res) => {
    const { refresh_token } = req.body || {};
    if (refresh_token) {
      await authService.logout(refresh_token);
    }
    res.status(204).send();
  })
);
