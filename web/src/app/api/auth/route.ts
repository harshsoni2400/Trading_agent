import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const { password } = await request.json();
  const appPassword = process.env.APP_PASSWORD || "trading123";

  if (password === appPassword) {
    const response = NextResponse.json({ success: true });
    response.cookies.set("auth_token", "authenticated", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      maxAge: 60 * 60 * 24, // 24 hours
    });
    return response;
  }

  return NextResponse.json({ error: "Invalid password" }, { status: 401 });
}
