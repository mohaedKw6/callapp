import { Router, type IRouter } from "express";
import healthRouter from "./health";
import botProxyRouter from "./botProxy";

const router: IRouter = Router();

router.use("/bot", botProxyRouter);
router.use(healthRouter);

export default router;
