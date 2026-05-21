defmodule RpsGame do
  def start_game do
    IO.puts("=== Rock Paper Scissors Game Server Started ===")
    {:ok, server} = GameServer.start_link()
    IO.puts("Server PID: #{inspect(server)}")
    IO.puts("Step 1: Players join with RpsGame.join_as_player(server, \"name\")")
    IO.puts("Step 2: Players play with RpsGame.play(server, \"name\")")
    server
  end

  def join_as_player(server, name) when is_pid(server) and is_binary(name) do
    IO.puts("=== #{name} joined the game ===")
    Player.join(server, name)
  end

  def play(server, name) when is_pid(server) and is_binary(name) do
    IO.puts("#{name}'s turn! Enter your hand (1=Rock, 2=Paper, 3=Scissors)")
    hand = get_hand(name)
    Player.play(server, name, hand)
    IO.puts("#{name} has played!")
  end

  defp get_hand(player_name) do
    input = IO.gets("#{player_name}の手 (1-3): ")
    case input do
      :eof ->
        IO.puts("入力が終了しました")
        1
      nil ->
        IO.puts("入力エラー")
        1
      _ ->
        case Integer.parse(String.trim(input)) do
          {hand, _} when hand in [1, 2, 3] -> hand
          _ ->
            IO.puts("1、2、または3を入力してください")
            get_hand(player_name)
        end
    end
  end
end
